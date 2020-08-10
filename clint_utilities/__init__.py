# Standard Library
import argparse
import datetime
import logging
from logging.config import dictConfig
import socket
import time
from typing import Any, Callable, Dict, List, Optional, Type

# Third Party Code
from dateutil.parser import parse
from dateutil.tz import tzoffset, tzutc
import requests


VERSION = "1.0.4"
__version__ = VERSION
version = [1, 0, 4]

_PARSED_DATES: Dict[str, datetime.datetime] = {}


logger = logging.getLogger(__name__)


class AlreadyInserted(Exception):
    pass


class RequestError(Exception):
    pass


class RequestSuccess(Exception):
    def __init__(self, response, *args, **kwargs):
        self.response = response
        super(RequestSuccess, self).__init__(*args, **kwargs)


class StoreSuccess(RequestSuccess):
    pass


class StoreError(RequestError):
    pass


def parse_utc_timestamp(ts: int, offset: int):
    dt = datetime.datetime.utcfromtimestamp(ts + offset)
    tz = tzoffset(name="Local", offset=offset)
    dt = dt.astimezone(tz=tz)
    return dt


def parse_date(date_string):
    if _PARSED_DATES.get(date_string) is None:
        _PARSED_DATES[date_string] = parse(date_string)
    return _PARSED_DATES[date_string]


def datetime_to_timestamp(dt):
    return int(
        datetime.datetime(
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=0,
            minute=0,
            second=0,
            tzinfo=tzutc(),
        ).timestamp()
    )


def date_string_to_timestamp(date):
    parsed_date = parse_date(date)
    return datetime_to_timestamp(parsed_date)


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
    # Validate
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
    try:
        make_durable_request(
            method=requests.get, url=url, num_attempts=num_attempts, delay=delay,
        )
    except RequestSuccess as exc:
        response = exc.response
    return response


def parse_args(configuration: Dict) -> argparse.Namespace:
    description: str = configuration["description"]
    args: Dict[str, Dict] = configuration["args"]
    parser = argparse.ArgumentParser(description=description)
    for arg, arg_data in iter(args.items()):
        parser.add_argument(*arg.split(","), **arg_data)
    return parser.parse_args()


def assert_raises(fn, args, kwargs, exc):
    try:
        fn(*args, **kwargs)
    except exc:
        return
    except Exception:
        assert False, "Did not raise %s" % exc
    assert False, "Did not raise %s" % exc


def setup_logging(
    log_level: str,
    extra_loggers: Optional[Dict] = None,
    msg_format: Optional[str] = None,
    formatter_class_name: Optional[str] = None,
):
    default_loggers: Dict[str, Dict] = {}
    loggers = extra_loggers and {**default_loggers, **extra_loggers} or default_loggers
    msg_format = (
        msg_format
        or "%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)s » %(message)s"
    )
    configuration: Dict[str, Any] = {
        "version": 1,
        "formatters": {"default": {"format": msg_format}},
        "handlers": {
            "default": {
                "level": log_level,
                "class": "logging.StreamHandler",
                "formatter": "default",
            }
        },
        "loggers": loggers,
    }
    if formatter_class_name:
        configuration["formatters"]["default"]["class"] = formatter_class_name
    dictConfig(configuration)
    logger.debug("Logging configuration: %s", configuration)
