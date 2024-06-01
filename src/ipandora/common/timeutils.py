# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : timeutils.py
@Time  : 2024-05-11
"""
import pendulum


class TimeUtils(object):
    DEFAULT_TIMEZONE = 'Asia/Shanghai'

    @staticmethod
    def get_current_timestamp(timezone=DEFAULT_TIMEZONE):
        """
        Get current timestamp
        :param timezone:
        :return:
        """
        return int(pendulum.now(timezone).timestamp())

    @staticmethod
    def get_current_timestamp_ms(timezone=DEFAULT_TIMEZONE):
        """
        Get current timestamp in milliseconds
        :param timezone:
        :return:
        """
        return int(pendulum.now(timezone).timestamp() * 1000)

    @staticmethod
    def get_timestamp_with_delta(years=0, months=0, days=0, hours=0, minutes=0, seconds=0,
                                 timezone=DEFAULT_TIMEZONE):
        """
        Get timestamp with delta
        :param years:
        :param months:
        :param days:
        :param hours:
        :param minutes:
        :param seconds:
        :param timezone:
        :return:
        """
        return int(pendulum.now(timezone).add(years=years, months=months, days=days, hours=hours,
                                              minutes=minutes, seconds=seconds).timestamp())

    @staticmethod
    def get_current_formattime(fmt="YYYY-MM-DD HH:mm:ss", timezone=DEFAULT_TIMEZONE):
        """
        Get current formatted datetime
        :param fmt:
        :param timezone:
        :return:
        """
        return pendulum.now(timezone).format(fmt)

    @staticmethod
    def get_current_datatime():
        """
        Get current datetime
        :return:
        """
        return pendulum.now()

    @staticmethod
    def get_iso_time(timezone=DEFAULT_TIMEZONE):
        """
        Get current ISO formatted time
        :param timezone:
        :return:
        """
        return pendulum.now(timezone).to_iso8601_string()

    @staticmethod
    def timestamp_to_formattime(timestamp, fmt="YYYY-MM-DD HH:mm:ss", timezone=DEFAULT_TIMEZONE):
        """
        Convert timestamp to formatted datetime
        :param timestamp:
        :param timezone:
        :param fmt:
        :return:
        """
        return pendulum.from_timestamp(timestamp, timezone).format(fmt)

    @staticmethod
    def timestamp_to_datetime(timestamp):
        """
        Convert timestamp to datetime
        :param timestamp:
        :return:
        """
        return pendulum.from_timestamp(timestamp)

    @staticmethod
    def formattime_to_timestamp(formattime, fmt="YYYY-MM-DD HH:mm:ss", timezone=DEFAULT_TIMEZONE):
        """
        Convert formatted datetime to timestamp
        :param formattime:
        :param fmt:
        :param timezone:
        :return:
        """
        return int(pendulum.from_format(formattime, fmt, timezone).timestamp())

    @staticmethod
    def datetime_to_timestamp(dt):
        """
        Convert datetime to timestamp
        :param dt:
        :return:
        """
        return int(dt.timestamp())

    @staticmethod
    def elapsed_to_formate_delta(elapsed):
        """
        Convert elapsed seconds to formatted delta
        :param elapsed:
        :return:
        """
        if elapsed < 0:
            raise ValueError("elapsed time must be greater than or equal to 0")
        days, seconds = divmod(elapsed, 86400)  # 86400s per day
        hours, seconds = divmod(seconds, 3600)  # 3600s per hour
        minutes, seconds = divmod(seconds, 60)  # 60s per minute
        parts = []
        if days > 0:
            parts.append(f"{days} Day{'s' if days > 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} Hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} Min{'s' if minutes > 1 else ''}")
        if seconds > 0 or not parts:
            parts.append(f"{seconds} Sec{'s' if seconds > 1 else ''}")
        return " | ".join(parts)


if __name__ == '__main__':
    tu = TimeUtils()
    print(tu.get_current_timestamp())
    print(tu.get_current_timestamp_ms())
    print(tu.get_current_formattime())
    print(tu.get_current_datatime())
    print(tu.get_iso_time())
    print(tu.elapsed_to_formate_delta(12.1420))

