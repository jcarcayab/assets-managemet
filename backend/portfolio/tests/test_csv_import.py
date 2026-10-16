from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from portfolio.models import Account, AccountType, Asset, CashFlow, Transaction
from portfolio.services import csv_import
from portfolio.services.positions import compute_positions

pytestmark = pytest.mark.django_db

CSV = """Fecha,Tipo,Simbolo,Cantidad,Precio,Comision,Monto,Notas,ID
2024-01-02,deposit,,,,,"$5,000.00",Transferencia,
01/03/2024,compra,VOO,10,400.50,1,,,
2024-02-01,dividend,VOO,,,,(12.34),,
2024-03-01,sell,VOO,4,450,,,,ord-9
2024-03-02,interes,,,,,"1,25",cuenta,
2024-03-03,bogus,VOO,1,1,,,,
2024-03-04,buy,VOO,,400,,,,
"""


def upload(api, account, text, dry_run=True):
    file = SimpleUploadedFile("movs.csv", text.encode(), content_type="text/csv")
    return api.post("/api/import/csv/", {"account": account.id, "file": file, "dry_run": dry_run}, format="multipart")


def test_parse_reports_errors_per_line(user, broker):
    parsed = csv_import.parse(broker, CSV)
    assert [r.kind for r in parsed.rows] == ["deposit", "buy", "dividend", "sell", "interest"]
    assert [(e["line"], e["error"][:14]) for e in parsed.errors] == [(7, "tipo desconoci"), (8, "falta quantity")]
    buy, div = parsed.rows[1], parsed.rows[2]
    assert (buy.quantity, buy.price, buy.fees) == (10, D("400.50"), 1)
    assert div.amount == D("12.34")  # (12.34) → the type gives the sign
    assert parsed.rows[4].amount == D("1.25")  # comma decimal
    assert parsed.new_symbols == ["VOO"]


def test_import_is_all_or_nothing_and_idempotent(api, user, broker):
    assert upload(api, broker, CSV, dry_run=False).status_code == 400  # errors → nothing written
    assert not Transaction.objects.exists()

    good = "\n".join(CSV.splitlines()[:6]) + "\n"
    preview = upload(api, broker, good).json()
    assert (preview["new_count"], preview["duplicate_count"], preview["new_symbols"]) == (5, 0, ["VOO"])
    assert not Transaction.objects.exists()  # a preview writes nothing

    done = upload(api, broker, good, dry_run=False).json()
    assert done["created"] == {"transactions": 4, "cash_flows": 1, "assets": 1, "duplicates": 0}
    voo = Asset.objects.get(owner=user, symbol="VOO")
    assert (voo.price_source, voo.source_id) == ("yahoo", "VOO")
    assert next(p for p in compute_positions(user) if p.symbol == "VOO").quantity == 6
    assert CashFlow.objects.get(account=broker).amount == 5000
    assert Transaction.objects.get(account=broker, kind="sell").external_id == "csv:ord-9"

    again = upload(api, broker, good, dry_run=False).json()
    assert again["created"]["duplicates"] == 5 and Transaction.objects.count() == 4


def test_other_users_account_is_refused(api, other_user):
    theirs = Account.objects.create(owner=other_user, name="X", account_type=AccountType.BROKERAGE)
    assert upload(api, theirs, CSV).status_code == 400


def test_missing_columns():
    from types import SimpleNamespace

    parsed = csv_import.parse(SimpleNamespace(owner=None, id=1), "symbol,quantity\nVOO,1\n")
    assert parsed.errors[0]["error"].startswith("faltan columnas: date, type")
