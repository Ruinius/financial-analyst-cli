from src.services.llm_client import clean_leading_json_wrapper, parse_partial_json


def test_clean_leading_json_wrapper():
    assert (
        clean_leading_json_wrapper('   ```json\n{\n  "thought": "hello"\n}\n```   ')
        == '{\n  "thought": "hello"\n}\n```'
    )
    assert clean_leading_json_wrapper("```\n{}\n```") == "{}\n```"
    assert clean_leading_json_wrapper('   { "test": 123 }   ') == '{ "test": 123 }'


def test_parse_partial_json_thought_only():
    partial_1 = '{\n  "thought": "I will start extraction'
    parsed_1 = parse_partial_json(partial_1)
    assert parsed_1 is not None
    assert parsed_1["thought"] == "I will start extraction"
    assert not parsed_1["_thought_finished"]
    assert "tool" not in parsed_1

    partial_2 = '{\n  "thought": "I will start extraction",\n'
    parsed_2 = parse_partial_json(partial_2)
    assert parsed_2 is not None
    assert parsed_2["thought"] == "I will start extraction"
    assert parsed_2["_thought_finished"]


def test_parse_partial_json_thought_and_tool():
    partial_1 = '{\n  "thought": "Find the sheet",\n  "tool": "get_chunk'
    parsed_1 = parse_partial_json(partial_1)
    assert parsed_1 is not None
    assert parsed_1["thought"] == "Find the sheet"
    assert parsed_1["_thought_finished"]
    assert parsed_1["tool"] == "get_chunk"
    assert not parsed_1["_tool_finished"]

    partial_2 = (
        '{\n  "thought": "Find the sheet",\n  "tool": "get_chunk",\n  "arguments": '
    )
    parsed_2 = parse_partial_json(partial_2)
    assert parsed_2 is not None
    assert parsed_2["tool"] == "get_chunk"
    assert parsed_2["_tool_finished"]


def test_parse_partial_json_arguments():
    # Object arguments streaming
    partial_1 = (
        '{\n  "thought": "X",\n  "tool": "Y",\n  "arguments": {\n    "chunk_id": 4'
    )
    parsed_1 = parse_partial_json(partial_1)
    assert parsed_1 is not None
    assert parsed_1["arguments"].strip() == '{\n    "chunk_id": 4'
    assert not parsed_1["_args_finished"]

    # Object arguments complete
    partial_2 = '{\n  "thought": "X",\n  "tool": "Y",\n  "arguments": {\n    "chunk_id": 4\n  }\n}'
    parsed_2 = parse_partial_json(partial_2)
    assert parsed_2 is not None
    assert parsed_2["arguments"].strip() == '{\n    "chunk_id": 4\n  }'
    assert parsed_2["_args_finished"]

    # String arguments streaming
    partial_3 = (
        '{\n  "thought": "X",\n  "tool": "Y",\n  "arguments": "some string value'
    )
    parsed_3 = parse_partial_json(partial_3)
    assert parsed_3 is not None
    assert parsed_3["arguments"] == "some string value"
    assert not parsed_3["_args_finished"]

    # String arguments complete
    partial_4 = (
        '{\n  "thought": "X",\n  "tool": "Y",\n  "arguments": "some string value"\n}'
    )
    parsed_4 = parse_partial_json(partial_4)
    assert parsed_4 is not None
    assert parsed_4["arguments"] == "some string value"
    assert parsed_4["_args_finished"]


def test_parse_partial_json_non_json():
    # If it does not start with '{', it should return None
    assert parse_partial_json("hello world") is None
    assert parse_partial_json("PASSED") is None
