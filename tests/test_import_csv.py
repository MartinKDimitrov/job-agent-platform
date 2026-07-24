"""Generic CSV company importer (BuiltWith / Derrick / any name+website+country export)."""
import app.tools.import_csv as imp


def _write(tmp_path, rows):
    p = tmp_path / "co.csv"
    p.write_text("\n".join(",".join(r) for r in rows), encoding="utf-8")
    return str(p)


def test_autodetects_columns_and_imports(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(imp, "upsert_company",
                        lambda db, name, **kw: seen.append((name, kw.get("website"), kw.get("country"))))
    class _S:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(imp, "SessionLocal", lambda: _S())
    path = _write(tmp_path, [
        ["Company Name", "Website", "Country"],
        ["Schaeffler", "schaeffler.hu", "HU"],
        ["SAP", "https://www.sap.com", "DE"],
    ])
    res = imp.run(path)
    assert res == {"imported": 2, "skipped": 0}
    assert ("Schaeffler", "https://schaeffler.hu", "HU") in seen
    assert ("SAP", "https://www.sap.com", "DE") in seen


def test_domain_gets_https_and_country_fallback(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(imp, "upsert_company",
                        lambda db, name, **kw: seen.append((name, kw.get("website"), kw.get("country"))))
    class _S:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(imp, "SessionLocal", lambda: _S())
    # 'domain' column, no country column -> falls back to --country default
    path = _write(tmp_path, [["name", "domain"], ["Acme", "acme.de"]])
    imp.run(path, default_country="de")
    assert seen == [("Acme", "https://acme.de", "DE")]


def test_rows_without_name_or_site_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "upsert_company", lambda db, name, **kw: None)
    class _S:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(imp, "SessionLocal", lambda: _S())
    path = _write(tmp_path, [["company", "website"], ["NoSite", ""], ["", "x.com"]])
    assert imp.run(path) == {"imported": 0, "skipped": 2}
