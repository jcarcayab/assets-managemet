def print_test_case_result(function_to_decorate):
    def wrapper(*args, **kw):
        try:
            function_to_decorate(*args, **kw)
        except AssertionError as e:
            print(f"[𐄂] {function_to_decorate.__name__}")
            raise e
        print(f"[✔] {function_to_decorate.__name__}")
    return wrapper