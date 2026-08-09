import pytest

from app.config import Settings
from app.db import build_session_factory
from app.models import Model
from app.services.catalog_import import (
    CatalogParseError,
    import_catalog_rows,
    parse_catalog_file,
)
from app.vector import ModelVectorStore, build_embedding_function


def _make_session_factory(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        chroma_db_path=str(tmp_path / "chroma"),
        mesh_api_key=None,
    )
    return build_session_factory(settings), settings


def _make_vector_store(settings, tmp_path):
    return ModelVectorStore(
        str(tmp_path / "chroma"),
        collection_name="models",
        embedding_function=build_embedding_function(settings),
    )


def test_parse_csv_file_reads_rows_and_splits_tags() -> None:
    content = (
        "title,provider,modality,price,description,use_case_tags\n"
        'Test Voice,Test Labs,Voice,$0.001/char,"A voice model.",real-time;support\n'
    ).encode("utf-8")
    rows = parse_catalog_file("catalog.csv", content)
    assert rows == [
        {
            "title": "Test Voice",
            "provider": "Test Labs",
            "modality": "Voice",
            "price": "$0.001/char",
            "description": "A voice model.",
            "use_case_tags": "real-time;support",
        }
    ]


def test_parse_json_file_accepts_bare_list_and_models_key() -> None:
    bare_list = b'[{"title": "A"}, {"title": "B"}]'
    assert parse_catalog_file("catalog.json", bare_list) == [
        {"title": "A"},
        {"title": "B"},
    ]

    wrapped = b'{"models": [{"title": "A"}]}'
    assert parse_catalog_file("catalog.json", wrapped) == [{"title": "A"}]


def test_parse_json_file_rejects_malformed_json() -> None:
    with pytest.raises(CatalogParseError):
        parse_catalog_file("catalog.json", b"{not json")


def test_parse_csv_file_rejects_missing_header() -> None:
    with pytest.raises(CatalogParseError):
        parse_catalog_file("catalog.csv", b"")


def test_parse_file_rejects_too_many_rows() -> None:
    rows = ",".join('{"title": "x"}' for _ in range(501))
    content = f"[{rows}]".encode("utf-8")
    with pytest.raises(CatalogParseError):
        parse_catalog_file("catalog.json", content)


def test_import_catalog_rows_inserts_valid_rows_and_syncs_vector_store(
    tmp_path,
) -> None:
    session_factory, settings = _make_session_factory(tmp_path)
    vector_store = _make_vector_store(settings, tmp_path)
    with session_factory() as session:
        results = import_catalog_rows(
            session,
            vector_store,
            [
                {
                    "title": "Test Voice",
                    "provider": "Test Labs",
                    "modality": "Voice",
                    "price": "$0.001/char",
                    "description": "A voice model.",
                    "latency_ms": "120",
                    "use_case_tags": "real-time;support",
                }
            ],
        )
        assert results == [
            {"row": 1, "title": "Test Voice", "status": "inserted", "errors": []}
        ]
        model = session.query(Model).filter(Model.title == "Test Voice").one()
        assert model.vector_synced is True
        assert model.latency_ms == 120
        assert model.use_case_tags == ["real-time", "support"]


def test_import_catalog_rows_reports_invalid_rows_without_aborting_batch(
    tmp_path,
) -> None:
    session_factory, settings = _make_session_factory(tmp_path)
    vector_store = _make_vector_store(settings, tmp_path)
    with session_factory() as session:
        results = import_catalog_rows(
            session,
            vector_store,
            [
                {"title": "", "provider": "Test Labs"},  # missing required fields
                {
                    "title": "Valid Model",
                    "provider": "Test Labs",
                    "modality": "LLM",
                    "price": "$1",
                    "description": "A model.",
                },
            ],
        )
        assert results[0]["status"] == "invalid"
        assert results[0]["errors"]
        assert results[1]["status"] == "inserted"
        assert session.query(Model).filter(Model.title == "Valid Model").count() == 1


def test_import_catalog_rows_skips_case_insensitive_duplicate_titles(tmp_path) -> None:
    session_factory, settings = _make_session_factory(tmp_path)
    vector_store = _make_vector_store(settings, tmp_path)
    with session_factory() as session:
        session.add(
            Model(
                title="Existing Model",
                description="d",
                provider="Test Labs",
                modality="LLM",
                price="$1",
                use_case_tags=[],
            )
        )
        session.commit()

        results = import_catalog_rows(
            session,
            vector_store,
            [
                {
                    "title": "existing model",
                    "provider": "Test Labs",
                    "modality": "LLM",
                    "price": "$1",
                    "description": "A model.",
                }
            ],
        )
        assert results == [
            {
                "row": 1,
                "title": "existing model",
                "status": "skipped_duplicate",
                "errors": [],
            }
        ]
        assert session.query(Model).count() == 1
