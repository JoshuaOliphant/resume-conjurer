# ABOUTME: Tests ATS vendor detection from job posting URLs in jd.txt.
# ABOUTME: Covers vendor subdomains, look-alike hosts, the first-match rule, and missing files.
import pytest

import ats


@pytest.mark.parametrize(
    ("url", "vendor"),
    [
        ("https://jobs.ashbyhq.com/elicit/d27d51d7-b318", "ashby"),
        ("https://job-boards.greenhouse.io/affirm/jobs/7819704003", "greenhouse"),
        ("https://boards-api.greenhouse.io/v1/boards/affirm/jobs/1?questions=true", "greenhouse"),
        ("https://acme.wd5.myworkdayjobs.com/en-US/External/job/123", "workday"),
        ("https://jobs.lever.co/acme/abc", "lever"),
        ("https://careers-acme.icims.com/jobs/1/job", "icims"),
        ("https://acme.eightfold.ai/careers?pid=1", "eightfold"),
        ("https://jobs.smartrecruiters.com/Acme/1", "smartrecruiters"),
        ("https://greenhouse.io/", "greenhouse"),
        ("https://notgreenhouse.io/jobs", None),
        ("https://acme.com/careers", None),
    ],
)
def test_vendor_of(url, vendor):
    assert ats.vendor_of(url) == vendor


def test_detect_ats_takes_the_first_recognized_url():
    text = "Blog: https://acme.com/eng\nSource: https://jobs.lever.co/acme/1\nhttps://jobs.ashbyhq.com/x"
    assert ats.detect_ats(text) == "lever"
    assert ats.detect_ats("No links here.") == "unknown"


def test_app_ats_reads_jd_txt(tmp_path):
    assert ats.app_ats(tmp_path) == "unknown"
    (tmp_path / "jd.txt").write_text("Source: https://job-boards.greenhouse.io/affirm/jobs/1\n")
    assert ats.app_ats(tmp_path) == "greenhouse"
