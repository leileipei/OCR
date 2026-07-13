import json

import pytest

from umi_web_spike.e10_evidence import E10Evidence


VALID = {
    "protocol": "oidc",
    "official_document_reference": "E10 客户开放平台/统一身份接口文档版本 10",
    "login_endpoint": "https://oa.example.internal/sso/authorize",
    "verification_endpoint": "https://oa.example.internal/sso/userinfo",
    "external_user_id_field": "user_id",
    "department_id_field": "department_id",
    "test_login_succeeded": True,
    "disabled_account_rejected": True,
    "logout_behavior_verified": True,
}


def test_accepts_complete_official_evidence():
    evidence = E10Evidence.from_dict(VALID)
    assert evidence.ready is True


def test_rejects_database_or_cookie_integration():
    for protocol in ("database", "shared_cookie", "html_scraping"):
        value = {**VALID, "protocol": protocol}
        try:
            E10Evidence.from_dict(value)
        except ValueError as error:
            assert "unsupported or unsafe protocol" in str(error)
        else:
            raise AssertionError(f"unsafe protocol accepted: {protocol}")


def test_requires_stable_user_and_department_identifiers():
    value = {**VALID, "external_user_id_field": ""}
    try:
        E10Evidence.from_dict(value)
    except ValueError as error:
        assert "external_user_id_field" in str(error)
    else:
        raise AssertionError("missing stable user id was accepted")


@pytest.mark.parametrize(
    "field",
    (
        "official_document_reference",
        "login_endpoint",
        "verification_endpoint",
        "external_user_id_field",
        "department_id_field",
    ),
)
@pytest.mark.parametrize("invalid_value", (None, 123))
def test_required_text_fields_reject_null_and_non_strings(field, invalid_value):
    value = {**VALID, field: invalid_value}

    with pytest.raises(ValueError, match=field):
        E10Evidence.from_dict(value)


@pytest.mark.parametrize(
    "field",
    (
        "test_login_succeeded",
        "disabled_account_rejected",
        "logout_behavior_verified",
    ),
)
def test_verification_results_must_be_json_booleans(field):
    value = {**VALID, field: "false"}

    with pytest.raises(ValueError, match=field):
        E10Evidence.from_dict(value)


@pytest.mark.parametrize("field", ("login_endpoint", "verification_endpoint"))
def test_https_endpoints_require_a_network_location(field):
    value = {**VALID, field: "https:///sso/endpoint"}

    with pytest.raises(ValueError, match=field):
        E10Evidence.from_dict(value)


def test_write_json_creates_parent_and_writes_utf8_ready_boolean(tmp_path):
    evidence = E10Evidence.from_dict(VALID)
    output = tmp_path / "nested" / "e10.json"

    evidence.write_json(output)

    raw = output.read_bytes()
    assert "E10 客户开放平台" in raw.decode("utf-8")
    payload = json.loads(raw)
    assert payload["ready"] is True
    assert isinstance(payload["ready"], bool)
