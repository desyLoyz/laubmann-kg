from laubmann_kg.normalization.dates import not_implemented


def test_date_normalization_placeholder() -> None:
    try:
        not_implemented()
    except NotImplementedError:
        pass
