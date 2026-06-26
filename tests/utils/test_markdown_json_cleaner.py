import json
from src.utils.markdown_helper import clean_json_text, extract_json_from_text


def test_clean_json_text_single_line_comments():
    raw = """{
        "company_name": "Salesforce", // The official company name
        "ticker": "CRM" // Ticker symbol
    }"""
    cleaned = clean_json_text(raw)
    data = json.loads(cleaned)
    assert data["company_name"] == "Salesforce"
    assert data["ticker"] == "CRM"


def test_clean_json_text_multi_line_comments():
    raw = """{
        /*
         * Multi-line comment describing the object
         */
        "reporting_currency": "USD",
        "fx_rate": 1.0 /* default FX rate */
    }"""
    cleaned = clean_json_text(raw)
    data = json.loads(cleaned)
    assert data["reporting_currency"] == "USD"
    assert data["fx_rate"] == 1.0


def test_clean_json_text_trailing_commas():
    # Objects
    raw_obj = '{"a": 1, "b": 2,}'
    assert json.loads(clean_json_text(raw_obj)) == {"a": 1, "b": 2}

    # Arrays
    raw_arr = "[1, 2, 3, ]"
    assert json.loads(clean_json_text(raw_arr)) == [1, 2, 3]

    # Nested
    raw_nested = """{
        "a": [1, 2,],
        "b": {
            "c": 3,
        },
    }"""
    assert json.loads(clean_json_text(raw_nested)) == {"a": [1, 2], "b": {"c": 3}}


def test_clean_json_text_preserves_strings():
    # Make sure we don't accidentally strip things inside double quotes
    raw = """{
        "url": "https://google.com",
        "comment_str": "This // is not a comment",
        "block_str": "This /* is not a block */ comment",
        "comma_str": "trailing comma, "
    }"""
    cleaned = clean_json_text(raw)
    data = json.loads(cleaned)
    assert data["url"] == "https://google.com"
    assert data["comment_str"] == "This // is not a comment"
    assert data["block_str"] == "This /* is not a block */ comment"
    assert data["comma_str"] == "trailing comma, "


def test_extract_json_from_text():
    text = """
    Here is the requested metadata:
    ```json
    {
        "ticker": "CRM", // Salesforce
        "fx_rate": 1.0,
    }
    ```
    Hope this helps!
    """
    json_str = extract_json_from_text(text)
    assert json_str is not None
    data = json.loads(json_str)
    assert data["ticker"] == "CRM"
    assert data["fx_rate"] == 1.0
