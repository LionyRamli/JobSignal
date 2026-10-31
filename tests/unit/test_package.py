import jobsignal


def test_package_exposes_version():
    assert jobsignal.__version__ == "0.1.0"
