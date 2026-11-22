from app import config


def test_readme_and_screenshots_exist():
    t = (config.ROOT_DIR / "README.md").read_text(encoding="utf-8")
    for s in [
        "pip install -r requirements.txt",
        "uvicorn app.main:app",
        "pytest",
        "SIMULATED",
        "MEASURED",
        "PROPOSED",
        "Assumptions",
        "Known limitations",
        "synthetic",
        "one year of weather",
        "PMMD",
        "SCA_PARAMS_PRESET",
    ]:
        assert s in t, s
    for n in ["hot_weekday", "cool_weekday", "semester_break"]:
        p = config.ROOT_DIR / "docs" / "screenshots" / f"{n}.png"
        assert p.stat().st_size > 50_000


def test_guide_pdf_exists_and_short():
    import re

    pdf = config.ROOT_DIR / "docs" / "user_guide.pdf"
    assert pdf.stat().st_size > 100_000
    pages = len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf.read_bytes()))
    assert 4 <= pages <= 9, pages
    html_path = config.ROOT_DIR / "docs" / "guide" / "user_guide.html"
    html = html_path.read_text(encoding="utf-8")
    low = html.lower()
    for s in ["simulated", "approve", "adjust", "random forest", "3d", "decision log"]:
        assert s in low, s
    for rel in re.findall(r'src="(img/[^"]+)"', html):
        assert (html_path.parent / rel).exists(), rel
