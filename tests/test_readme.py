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
