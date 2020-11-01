# TODO: Almost all the functions in this file need
# documentation, typing information, and cleaned-up
# names

# Standard Library
import argparse
import datetime
import logging
from logging.config import dictConfig
import socket
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Type

# Third Party Code
from dateutil.parser import parse
from dateutil.tz import tzoffset, tzutc
import requests


VERSION = "1.2.1"
__version__ = VERSION
version = [1, 2, 1]

_PARSED_DATES: Dict[str, datetime.datetime] = {}


logger = logging.getLogger(__name__)


class AlreadyInserted(Exception):
    """
    Indicates that the data was previously inserted
    """

    pass


class RequestError(Exception):
    """
    Indicates that the request failed.
    """

    pass


class RequestSuccess(Exception):
    """
    Indicates that the request succeeded.

    :param response: The response to the successful request.
    """

    def __init__(self, response: requests.Response):
        self.response = response
        super(RequestSuccess, self).__init__()


class StoreSuccess(RequestSuccess):
    """
    Indicates that the storage request was successfully completed.
    """

    pass


class StoreError(RequestError):
    """
    Indicates that the storage request failed.
    """

    pass


def parse_utc_timestamp(ts: int, offset: int) -> datetime.datetime:
    """
    Converts an epoch-base timestamp and offset to a timezone-aware datetime object.

    :param ts: An integer representing the number of seconds since Jan 1, 1970 UTC
    :param offset: An integer indicating the number of seconds west (negative) or west (positive) of the date line.
    :returns: A timezone aware datetime object representing the moment specified in the timestamp.
    """
    return (
        datetime.datetime.utcfromtimestamp(ts)
        .replace(tzinfo=datetime.timezone.utc)
        .astimezone(tzoffset(name="Local", offset=offset))
    )


def parse_date_string(date_string: str) -> datetime.datetime:
    """
    Parses a string containing a date and produces a (potentially time-zone aware) datetime object.

    :returns: A (potentially time-zone aware) datetime object representing the moment specified in the string.
    :param date_string: A string representing a date and time.
    """
    if _PARSED_DATES.get(date_string) is None:
        _PARSED_DATES[date_string] = parse(date_string)
    return _PARSED_DATES[date_string]


def datetime_to_date_timestamp(dt: datetime.datetime) -> int:
    """
    Converts a datetime object to a timestamp representing the first second of the day specified in the input.

    Given a datetime object representing any moment in time, return an integer timestamp representing the first
    second of the day of the moment.

    :param dt: Any datetime object. If the object is not tz-aware, we will presume UTC.
    :returns: An integer timestamp representing the first second of the day of the input datetime, in UTC.
    """
    tz = dt.tzinfo or tzutc()
    return int(
        datetime.datetime(
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=0,
            minute=0,
            second=0,
            tzinfo=tz,
        ).timestamp()
    )


def date_string_to_date_timestamp(date_string: str) -> int:
    """
    Convert a date string to a date timestamp.

    Input could be any kind of date or datetime string, but only the date portion will be extracted
    and used.

    :param date_string: A string representing a date. If a datetime is specified, only the date portion will be used.
    """
    parsed_date = parse_date_string(date_string)
    return datetime_to_date_timestamp(parsed_date)


def make_durable_request(
    method: Callable[..., requests.Response],
    url: str,
    num_attempts: int,
    delay: float,
    success_codes: Optional[List[int]] = None,
    success: Optional[Type[RequestSuccess]] = None,
    error: Optional[Type[RequestError]] = None,
    json: Optional[Dict] = None,
) -> None:
    """
    Make a durable HTTP request.

    Durable means that efforts will be made to ensure that the requested operation has been completed
    despite any kind of transient failures.

    The caller of this method should be able to know definitively whether or not their requested operation
    actually succeeded or will never succeed.

    If the request is made, but network or socket errors occur, a delay will in incurred, and the operation
    will be attempted again until the maximum number of tries is exceeded or the operation succeeds.

    If a server error (5XX) occurs, the retry mechanism will similarly engage.

    Any other kind of error will result in an abortion of the retry mechanism, since subsequent
    attempts at completing the request would be futile.

    :param method: A function that returns a `requests.Response` object.
    :param url: An HTTP URL to make a request to.
    :param num_attempts: The maximum number of requests to attempt before giving up.
    :param delay: The amount of time to delay (in seconds), before making subsequent requests.
    :success_codes: An optional list of HTTP codes that should be considered "successful"
                    (default: [200, 201, 202, 204]).
    :success: An optional exception to raise in the case of success. (default: `RequestSuccess`).
    :error: An optional exceptio nto raise in the case of failure (default: `RequestError`).
    :json: An optional payload to convert to JSON and include in the body when making the request.
    :returns: None
    :raises: Different exceptions depending on whether or not the operation succeeded or failed. An exception
             signalling success will carry a `response` property bearing the entire response object.

    """
    if num_attempts <= 0:
        raise ValueError("The value of `num_attempts` must be greater than 0.")
    if delay < 0:
        raise ValueError("The value of `delay` must be greater than or equal to 0.")
    success = success or RequestSuccess
    error = error or RequestError
    success_codes = success_codes or [200, 201, 202, 204]
    response: Optional[requests.Response] = None
    # Execute request.
    try:
        if json:
            response = method(url=url, json=json)
        else:
            response = method(url=url)
    except (requests.exceptions.ConnectionError, socket.timeout):
        logger.warning("Network error.")

    # Process outcomes.
    if response is not None:
        if response.status_code >= 500 and response.status_code < 600:
            logger.warning("Server error.")
        elif response.status_code in success_codes:
            logger.info("Request was successful.")
            raise success(response=response)
        else:
            logger.error(
                "Could not complete request due to status code %s: %s",
                response.status_code,
                response.text,
            )
            raise error(
                "Could not complete request due to stauts code %s: %s"
                % (response.status_code, response.text)
            )

    if num_attempts > 1:
        logger.info("Will retry request.")
        time.sleep(delay)
        make_durable_request(
            method=method,
            url=url,
            num_attempts=(num_attempts - 1),
            delay=delay * 2,
            success_codes=success_codes,
            success=success,
            error=error,
            json=json,
        )
    else:
        raise error("Unable to complete request.")


def make_durable_post(
    url: str, num_attempts: int, delay: float, json: Dict
) -> requests.Response:
    """
    Make a durable POST operation.

    First read the documentation to `make_durable_request` as this method leverages that code.

    We provide all the user-supplied data, but prefill `method`, `success_codes`, `success,` and `error`
    to provide an nice developer experience for HTTP POST requests.

    :param url: The URL to make the request to.
    :param num_attempts: The maximum number of attempts to make in the face of transient errors.
    :param delay: How many seconds to delay between retries.
    :param json: A payload object that will be converted to JSON and used as the body of the POST request.
    :returns: An HTTP response object.
    """
    try:
        make_durable_request(
            method=requests.post,
            url=url,
            num_attempts=num_attempts,
            delay=delay,
            success_codes=[201, 409],
            success=StoreSuccess,
            error=StoreError,
            json=json,
        )
    except StoreSuccess as exc:
        response = exc.response
    return response


def make_durable_get(url: str, num_attempts: int, delay: float) -> requests.Response:
    """
    Make a durable GET operation.

    First read the documentation to `make_durable_request` as this method leverages that code.

    We provide all the user-supplied data, but prefill `method` to provide an nice developer
    experience for HTTP GET requests.

    :param url: The URL to make the request to.
    :param num_attempts: The maximum number of attempts to make in the face of transient errors.
    :param delay: How many seconds to delay between retries.
    :returns: An HTTP response object.
    """
    try:
        make_durable_request(
            method=requests.get, url=url, num_attempts=num_attempts, delay=delay,
        )
    except RequestSuccess as exc:
        response = exc.response
    return response


def parse_args(configuration: Dict) -> argparse.Namespace:
    """
    Parses program arguments according to a configuration dictionary

    The configuration looks a little bit like the following. Keys for the
    "args" dictionary can contain either only a short or long argument
    name, or can supply both but placing a comma in between them.

    {
        "description": "My program",
        "args": {
            "-C,--color": {
                "type": "int",
                "help": "The color to use"
                "default": 255
            },
            "--name": {
                "type": "str",
                "help": "Your name",
            }
        }
    }

    :param configuration: A dictionary that matches the format above.
    :returns: A completed parsed argument namespace.
    """
    description: str = configuration["description"]
    args: Dict[str, Dict] = configuration["args"]
    parser = argparse.ArgumentParser(description=description)
    for arg, arg_data in iter(args.items()):
        parser.add_argument(*arg.split(","), **arg_data)
    return parser.parse_args()


def assert_raises(
    fn: Callable, args: Iterable[Any], kwargs: Dict[str, Any], exc: Type[Exception]
) -> None:
    """
    Asserts that a specific exception was raised while executing a function.

    If the exception is raised, this method returns. If it is _not_ raised,
    an `AssertionError` is raised.

    :param fn: A callable that can accept the provided args and kwargs and should raise
               the specified exception.
    :param args: A list of positional arguments to apply to the function.
    :param kwargs: A dictionary of named arguments to apply to the function.
    :param exc: An exception that the function should raise.
    :returns: None
    :raises AssertionError: If the specified exception was not raised while executing the function.
    """
    try:
        fn(*args, **kwargs)
    except exc:
        return
    except Exception:
        pass
    assert False, "Did not raise %s" % exc


def setup_logging(
    log_level: str,
    msg_format: Optional[str] = None,
    formatter_class_name: Optional[str] = None,
) -> None:
    """
    Sets up the logging system.

    :param log_level: The logging level to configure the logging system for. Will be applied globally.
    :param msg_format: The format to use for the logging output. (Defaults to a sane option).
    :param formatted_class_name: Optionally provide a custom log formatter class.
    """
    msg_format = (
        msg_format
        or "%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)s » %(message)s"
    )
    configuration: Dict[str, Any] = {
        "version": 1,
        "formatters": {"default": {"format": msg_format}},
        "handlers": {
            "console": {
                "level": log_level,
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "level": log_level,
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": "error.log",
                "maxBytes": 1024 * 1024 * 1024,
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console", "file"],
            "propagate": True,
        },
        "disable_existing_loggers": True,
    }
    if formatter_class_name:
        configuration["formatters"]["default"]["class"] = formatter_class_name
    dictConfig(configuration)
    logger.debug("Logging configuration: %s", configuration)
