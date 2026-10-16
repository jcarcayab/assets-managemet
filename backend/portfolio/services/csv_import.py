"""Import movements into one account from a CSV file (for accounts without a connection, or older history).

Columns (header row, any order; Spanish names work too):
    date, type, symbol, quantity, price, fees, amount, notes, id

- type: buy, sell, dividend, interest, fee, staking, split (ledger) or deposit, withdrawal, employer (money in/out).
- buy/sell/staking need quantity and price; dividend/interest/fee and deposits need amount; split needs quantity.
- Unknown symbols become new assets priced from Yahoo Finance (edit them afterwards if that's wrong).
- Re-importing the same file adds nothing: each row is keyed by `id` when given, otherwise by its content.
"""

import csv
import datetime as dt
import hashlib
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction as db_tx

from portfolio.models import Account, Asset, AssetClass, CashFlow, CashFlowKind, PriceSource, Transaction, TransactionKind
from portfolio.services.positions import cash_asset

MAX_ROWS = 20_000
PREFIX = "csv:"

ALIASES = {
    "date": ("date", "fecha"),
    "type": ("type", "tipo", "kind", "action", "accion", "acción"),
    "symbol": ("symbol", "simbolo", "símbolo", "ticker", "activo", "asset"),
    "quantity": ("quantity", "cantidad", "qty", "shares", "units", "unidades"),
    "price": ("price", "precio"),
    "fees": ("fees", "fee", "comision", "comisión", "comisiones", "commission"),
    "amount": ("amount", "monto", "importe", "total"),
    "notes": ("notes", "notas", "description", "descripcion", "descripción", "concepto"),
    "id": ("id", "external_id", "order_id", "order id", "transaction id"),
}
TYPES = {
    "buy": TransactionKind.BUY, "compra": TransactionKind.BUY,
    "sell": TransactionKind.SELL, "venta": TransactionKind.SELL,
    "dividend": TransactionKind.DIVIDEND, "dividendo": TransactionKind.DIVIDEND,
    "interest": TransactionKind.INTEREST, "interes": TransactionKind.INTEREST, "interés": TransactionKind.INTEREST,
    "fee": TransactionKind.FEE, "comision": TransactionKind.FEE, "comisión": TransactionKind.FEE,
    "staking": TransactionKind.STAKING, "reward": TransactionKind.STAKING,
    "split": TransactionKind.SPLIT,
    "deposit": CashFlowKind.DEPOSIT, "deposito": CashFlowKind.DEPOSIT, "depósito": CashFlowKind.DEPOSIT,
    "withdrawal": CashFlowKind.WITHDRAWAL, "retiro": CashFlowKind.WITHDRAWAL,
    "employer": CashFlowKind.EMPLOYER, "match": CashFlowKind.EMPLOYER,
}
FLOW_KINDS = {CashFlowKind.DEPOSIT, CashFlowKind.WITHDRAWAL, CashFlowKind.EMPLOYER}
NEEDS = {
    TransactionKind.BUY: ("quantity", "price"),
    TransactionKind.SELL: ("quantity", "price"),
    TransactionKind.STAKING: ("quantity", "price"),
    TransactionKind.SPLIT: ("quantity",),
    TransactionKind.DIVIDEND: ("amount",),
    TransactionKind.INTEREST: ("amount",),
    TransactionKind.FEE: ("amount",),
}


@dataclass
class Row:
    line: int
    kind: str
    date: dt.date
    symbol: str = ""
    quantity: Decimal = Decimal(0)
    price: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    amount: Decimal = Decimal(0)
    notes: str = ""
    ext_id: str = ""
    status: str = "new"  # new | duplicate


@dataclass
class Parsed:
    rows: list[Row] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    new_symbols: list[str] = field(default_factory=list)


def _number(raw: str) -> Decimal | None:
    """Accepts 1,234.56 · $1,234.56 · (12.50) · -12.5 · 12,5 (comma decimal when there's no dot)."""
    text = (raw or "").strip().replace("$", "").replace(" ", "")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    if "," in text and "." not in text and text.count(",") == 1 and len(text.split(",")[1]) != 3:
        text = text.replace(",", ".")
    text = text.replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"número inválido: {raw!r}") from None
    return -value if negative else value


def _date(raw: str) -> dt.date:
    text = (raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"fecha inválida: {raw!r} (usa AAAA-MM-DD o MM/DD/AAAA)")


def _columns(header: list[str]) -> dict[str, int]:
    names = [h.strip().lower() for h in header]
    cols = {}
    for key, aliases in ALIASES.items():
        for i, name in enumerate(names):
            if name in aliases:
                cols[key] = i
                break
    missing = [k for k in ("date", "type") if k not in cols]
    if missing:
        raise ValueError(f"faltan columnas: {', '.join(missing)}")
    return cols


def _content_id(account: Account, row: Row) -> str:
    key = "|".join(str(v) for v in (account.id, row.kind, row.date, row.symbol, row.quantity, row.price, row.fees,
                                     row.amount, row.notes))
    return hashlib.sha1(key.encode()).hexdigest()[:24]


def parse(account: Account, text: str) -> Parsed:
    out = Parsed()
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text.lstrip("﻿")), dialect)
    try:
        cols = _columns(next(reader))
    except StopIteration:
        out.errors.append({"line": 1, "error": "el archivo está vacío"})
        return out
    except ValueError as exc:
        out.errors.append({"line": 1, "error": str(exc)})
        return out

    known = set(Asset.objects.filter(owner=account.owner).values_list("symbol", flat=True))
    new_symbols: set[str] = set()
    seen: set[str] = set()
    for line, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(out.rows) + len(out.errors) >= MAX_ROWS:
            out.errors.append({"line": line, "error": f"máximo {MAX_ROWS} filas por archivo"})
            break

        def cell(key):
            i = cols.get(key)
            return cells[i].strip() if i is not None and i < len(cells) else ""

        try:
            kind = TYPES.get(cell("type").lower())
            if kind is None:
                raise ValueError(f"tipo desconocido: {cell('type')!r}")
            row = Row(line=line, kind=kind, date=_date(cell("date")), notes=cell("notes")[:500])
            for key in ("quantity", "price", "fees", "amount"):
                value = _number(cell(key))
                if value is not None:
                    setattr(row, key, abs(value))  # the type gives the direction
            if kind in FLOW_KINDS:
                if not row.amount:
                    raise ValueError("falta el monto")
            else:
                row.symbol = cell("symbol").upper()
                if kind != TransactionKind.INTEREST and not row.symbol:
                    raise ValueError("falta el símbolo")
                for need in NEEDS.get(kind, ()):
                    if not getattr(row, need):
                        raise ValueError(f"falta {need}")
                if row.symbol and row.symbol not in known:
                    new_symbols.add(row.symbol)
        except ValueError as exc:
            out.errors.append({"line": line, "error": str(exc)})
            continue

        row.ext_id = PREFIX + (cell("id")[:90] or _content_id(account, row))
        if row.ext_id in seen:
            row.status = "duplicate"
        seen.add(row.ext_id)
        out.rows.append(row)

    ids = [r.ext_id for r in out.rows]
    existing = set(Transaction.objects.filter(account=account, external_id__in=ids).values_list("external_id", flat=True))
    existing |= set(CashFlow.objects.filter(account=account, external_id__in=ids).values_list("external_id", flat=True))
    for r in out.rows:
        if r.ext_id in existing:
            r.status = "duplicate"
    out.new_symbols = sorted(new_symbols)
    return out


def apply(account: Account, parsed: Parsed) -> dict:
    """Write the new rows (all or nothing). Duplicates are skipped."""
    owner = account.owner
    created = {"transactions": 0, "cash_flows": 0, "assets": 0, "duplicates": 0}
    with db_tx.atomic():
        assets = {a.symbol: a for a in Asset.objects.filter(owner=owner)}
        for symbol in parsed.new_symbols:
            assets[symbol] = Asset.objects.create(
                owner=owner, symbol=symbol, name=symbol, asset_class=AssetClass.STOCK,
                price_source=PriceSource.YAHOO, source_id=symbol,
            )
            created["assets"] += 1
        for r in parsed.rows:
            if r.status == "duplicate":
                created["duplicates"] += 1
                continue
            if r.kind in FLOW_KINDS:
                CashFlow.objects.create(
                    account=account, kind=r.kind, date=r.date, amount=r.amount, notes=r.notes, external_id=r.ext_id
                )
                created["cash_flows"] += 1
                continue
            asset = assets[r.symbol] if r.symbol else cash_asset(owner)
            Transaction.objects.create(
                account=account, asset=asset, kind=r.kind, date=r.date, quantity=r.quantity, price=r.price,
                fees=r.fees, amount=r.amount, notes=r.notes, external_id=r.ext_id,
            )
            created["transactions"] += 1
    return created


def preview(parsed: Parsed) -> dict:
    return {
        "rows": [
            {
                "line": r.line, "kind": r.kind, "date": r.date, "symbol": r.symbol, "quantity": r.quantity,
                "price": r.price, "fees": r.fees, "amount": r.amount, "notes": r.notes, "status": r.status,
            }
            for r in parsed.rows
        ],
        "errors": parsed.errors,
        "new_symbols": parsed.new_symbols,
        "new_count": sum(r.status == "new" for r in parsed.rows),
        "duplicate_count": sum(r.status == "duplicate" for r in parsed.rows),
    }
