import json
from pathlib import Path

from app.automation import real_amazon_pipeline as pipeline


class _EmptyQuery:
    def all(self):
        return []


class _EmptySession:
    def query(self, *_args):
        return _EmptyQuery()

    def close(self):
        pass


def _product(asin: str, url: str) -> pipeline.Product:
    return pipeline.Product(
        marketplace_code="BR",
        asin=asin,
        title="Produto",
        price_display="",
        image_url="",
        detail_url=url,
        source="test",
    )


def test_product_matches_real_and_masked_asin():
    real_asin = "B09HR3QHL8"
    product = _product(
        pipeline._stable_asin(real_asin),
        f"https://www.amazon.com.br/dp/{real_asin}",
    )

    assert ("BR", real_asin) in pipeline.product_identity_keys(product)
    assert ("BR", pipeline._stable_asin(real_asin)) in pipeline.product_identity_keys(product)


def test_pending_keys_include_bio_history(monkeypatch, tmp_path):
    real_asin = "B09HR3QHL8"
    history_path = tmp_path / "_bio_historico.json"
    history_path.write_text(
        json.dumps(
            {
                f"BR:{real_asin}": {
                    "market": "BR",
                    "asin": real_asin,
                    "url": f"https://www.amazon.com.br/dp/{real_asin}",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(pipeline, "BIO_HISTORY_PATH", history_path)
    monkeypatch.setattr(pipeline, "PENDING_DIRECTORY", tmp_path / "pending")
    monkeypatch.setattr(pipeline, "PROCESSED_DIRECTORY", tmp_path / "processed")
    monkeypatch.setattr(pipeline, "OUTPUT_DIRECTORY", tmp_path / "outputs")
    monkeypatch.setattr(pipeline, "RESERVATION_DIRECTORY", tmp_path / "reservations")

    from app.core import database

    monkeypatch.setattr(database, "SessionLocal", _EmptySession)
    keys = pipeline.pending_product_keys()

    product = _product(
        pipeline._stable_asin(real_asin),
        f"https://www.amazon.com.br/dp/{real_asin}",
    )
    assert pipeline.product_was_processed(product, keys)


def test_product_reservation_is_atomic(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "RESERVATION_DIRECTORY", tmp_path)
    real_asin = "B09HR3QHL8"
    masked = _product(
        pipeline._stable_asin(real_asin),
        f"https://www.amazon.com.br/dp/{real_asin}",
    )
    unmasked = _product(real_asin, f"https://www.amazon.com.br/dp/{real_asin}")

    assert pipeline.reserve_product(masked) is True
    assert pipeline.reserve_product(unmasked) is False

    pipeline.release_product_reservation(masked)
    assert pipeline.reserve_product(unmasked) is True
    pipeline.release_product_reservation(unmasked)


def test_root_is_derived_from_repository_file():
    expected = Path(pipeline.__file__).resolve().parents[2]
    assert pipeline._DEFAULT_ROOT == expected
