"""Tests for portfolio manager JSON parsing and user-facing errors."""

from src.utils.portfolio_json import parse_hedge_fund_response


def test_parse_none():
    assert parse_hedge_fund_response(None) is None


def test_parse_valid_json():
    assert parse_hedge_fund_response('{"AAPL": {"action": "hold", "quantity": 0}}') == {
        "AAPL": {"action": "hold", "quantity": 0}
    }


def test_parse_echo_prompt_hint(capsys):
    assert parse_hedge_fund_response("Make trading decisions based on the provided data.") is None
    err = capsys.readouterr().out
    assert "echo" in err.lower()
    assert "JSON" in err


def test_parse_non_json_prose(capsys):
    assert parse_hedge_fund_response("Here are my thoughts in plain English.") is None
    err = capsys.readouterr().out
    assert "not valid JSON" in err
