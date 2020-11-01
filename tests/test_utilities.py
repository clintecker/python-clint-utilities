# Standard Library
import datetime
import json
from unittest import mock

# Third Party Code
from dateutil.tz import tzoffset
import requests
import responses

# Clint Utilities Code
from clint_utilities import (
    _PARSED_DATES,
    assert_raises,
    date_string_to_timestamp,
    datetime_to_timestamp,
    make_durable_get,
    make_durable_post,
    make_durable_request,
    parse_args,
    parse_date,
    parse_utc_timestamp,
    RequestError,
    RequestSuccess,
    setup_logging,
)


def test_parse_date():
    assert len(_PARSED_DATES) == 0
    assert datetime.datetime(
        2020, 6, 20, 14, 39, 10, tzinfo=tzoffset(None, -21600)
    ) == parse_date("2020-06-20T14:39:10-0600")
    assert len(_PARSED_DATES) == 1
    # Test caching
    assert datetime.datetime(
        2020, 6, 20, 14, 39, 10, tzinfo=tzoffset(None, -21600)
    ) == parse_date("2020-06-20T14:39:10-0600")
    assert len(_PARSED_DATES) == 1


def test_parse_utc_timestamp():
    assert datetime.datetime(
        2020, 7, 7, 15, 1, 56, tzinfo=tzoffset("Local", -21600)
    ) == parse_utc_timestamp(ts=1594155716, offset=-21600)


def test_datetime_to_timestamp():
    assert 1592611200 == datetime_to_timestamp(
        datetime.datetime(2020, 6, 20, 14, 39, 10)
    )


def test_date_string_to_timestamp():
    assert 1592611200 == date_string_to_timestamp("2020-06-20")


def test_make_durable_request_num_attempts_value_error():
    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=requests.get, url="http://example.com", num_attempts=0, delay=1.0
        ),
        args=(),
        exc=ValueError,
    )


def test_make_durable_request_delay_value_error():
    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=requests.get, url="http://example.com", num_attempts=3, delay=-1.0
        ),
        args=(),
        exc=ValueError,
    )


@responses.activate
def test_make_durable_request_without_json():
    responses.add(
        method=responses.GET,
        url="http://google.com/",
        status=200,
        body="Cool.",
        headers={"Content-Type": "text/plain"},
    )
    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=requests.get,
            url="http://google.com/",
            success_codes=[200,],
            num_attempts=2,
            delay=2.0,
        ),
        args=(),
        exc=RequestSuccess,
    )


@responses.activate
def test_make_durable_request_1_bad_response():
    responses.add(method=responses.POST, url="https://example.com/resource", status=504)
    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=requests.post,
            url="https://example.com/resource",
            num_attempts=1,
            delay=5,
            json={"resources": [{"id": 1}, {"id": 2}, {"id": 3}]},
        ),
        args=(),
        exc=RequestError,
    )


@responses.activate
def test_make_durable_request_succeeds_after_retry():
    responses.add(method=responses.POST, url="https://example.com/resource", status=504)
    responses.add(method=responses.POST, url="https://example.com/resource", status=201)
    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=requests.post,
            url="https://example.com/resource",
            num_attempts=3,
            delay=0,
            json={"resources": [{"id": 1}, {"id": 2}, {"id": 3}]},
        ),
        args=(),
        exc=RequestSuccess,
    )


@responses.activate
def test_make_durable_request_client_error():
    responses.add(method=responses.POST, url="https://example.com/resource", status=400)
    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=requests.post,
            url="https://example.com/resource",
            num_attempts=3,
            delay=0,
            json={"resources": [{"id": 1}, {"id": 2}, {"id": 3}]},
        ),
        args=(),
        exc=RequestError,
    )


@responses.activate
def test_make_durable_request_connection_error():
    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=requests.post,
            url="https://example.com/resource",
            num_attempts=3,
            delay=0,
            json={"resources": [{"id": 1}, {"id": 2}, {"id": 3}]},
        ),
        args=(),
        exc=RequestError,
    )


def test_make_durable_request_unhandled_error():
    def method(*args, **kwargs):
        raise ValueError()

    assert_raises(
        fn=make_durable_request,
        kwargs=dict(
            method=method,
            url="http://127.0.0.1:8000/resource",
            num_attempts=3,
            delay=0,
            json={"resources": [{"id": 1}, {"id": 2}, {"id": 3}]},
        ),
        args=(),
        exc=ValueError,
    )


@responses.activate
def test_make_durable_post():
    responses.add(
        url="http://example.com/resource",
        method=responses.POST,
        status=201,
        body=json.dumps({"data": {"resource": {"id": 1}}}),
        headers={"Content-Type": "application/json"},
    )
    response = make_durable_post(
        "http://example.com/resource", 3, 1.0, json={"resource": {"id": 1}}
    )
    assert response.json() == {"data": {"resource": {"id": 1}}}


@responses.activate
def test_make_durable_get():
    responses.add(
        url="http://example.com/resource/1",
        method=responses.GET,
        status=200,
        body="Cool",
        headers={"Content-Type": "text/plain"},
    )
    response = make_durable_get("http://example.com/resource/1", 3, 1.0)
    assert "Cool" == response.text


@mock.patch("clint_utilities.argparse.ArgumentParser")
def test_parse_args(mock_arg_parse_cls):
    mock_parser = mock.Mock(name="parser")
    mock_arg_parse_cls.return_value = mock_parser
    parse_args(
        {
            "description": "This is what my tool does!",
            "args": {
                "--option,-O": {
                    "dest": "option_cool",
                    "type": float,
                    "default": 0.00,
                    "help": "Please input the option value!",
                },
                "--flag,-F": {
                    "dest": "mean_flag",
                    "type": bool,
                    "action": "store_true",
                    "default": False,
                    "help": "Do you want to be mean??",
                },
            },
        }
    )
    assert mock_arg_parse_cls.called_with(description="This is what my tool does!")
    assert [
        mock.call.add_argument(
            "--option",
            "-O",
            dest="option_cool",
            type=float,
            default=0.0,
            help="Please input the option value!",
        ),
        mock.call.add_argument(
            "--flag",
            "-F",
            dest="mean_flag",
            type=bool,
            action="store_true",
            default=False,
            help="Do you want to be mean??",
        ),
        mock.call.parse_args(),
    ] == mock_parser.method_calls


def test_assert_raises():
    def oops():
        raise ValueError

    def oops2():
        raise TypeError

    def oops3():
        return 3

    assert_raises(fn=oops, args=tuple(), kwargs=dict(), exc=ValueError)

    assert_raises(
        fn=assert_raises,
        args=tuple(),
        kwargs=dict(fn=oops2, args=tuple(), kwargs={}, exc=ValueError),
        exc=AssertionError,
    )

    assert_raises(
        fn=assert_raises,
        args=tuple(),
        kwargs=dict(fn=oops3, args=tuple(), kwargs={}, exc=ValueError),
        exc=AssertionError,
    )


@mock.patch("clint_utilities.dictConfig")
def test_setup_logging(mock_dict_config):
    setup_logging(
        "DEBUG",
        msg_format="%(asctime)s: %(message)s",
        formatter_class_name="project.utils.RequestFormatter",
    )
    mock_dict_config.assert_called_once_with(
        {
            "version": 1,
            "formatters": {
                "default": {
                    "format": "%(asctime)s: %(message)s",
                    "class": "project.utils.RequestFormatter",
                }
            },
            "handlers": {
                "console": {
                    "level": "DEBUG",
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
                "file": {
                    "level": "DEBUG",
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "filename": "error.log",
                    "maxBytes": 1073741824,
                },
            },
            "root": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": True,
            },
            "disable_existing_loggers": True,
        }
    )


@mock.patch("clint_utilities.dictConfig")
def test_setup_logging_no_request_class(mock_dict_config):
    setup_logging(
        "DEBUG", msg_format="%(asctime)s: %(message)s",
    )
    mock_dict_config.assert_called_once_with(
        {
            "version": 1,
            "formatters": {"default": {"format": "%(asctime)s: %(message)s"}},
            "handlers": {
                "console": {
                    "level": "DEBUG",
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
                "file": {
                    "level": "DEBUG",
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "filename": "error.log",
                    "maxBytes": 1073741824,
                },
            },
            "root": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": True,
            },
            "disable_existing_loggers": True,
        }
    )
