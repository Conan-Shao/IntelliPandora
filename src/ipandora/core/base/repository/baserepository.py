# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : baserepository.py
@Time  : 2024-05-23
"""
from typing import Any, Optional
from pymysql.connections import Connection
from pymysql.err import MySQLError
from ipandora.common.mysqlaction import MysqlAction
from ipandora.common.timeutils import TimeUtils
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.log import logger


class BaseRepository(object):
    def __init__(self, db_config = None):
        _tmp_config = {'host': Runtime.Mysql.host,
                       'username': Runtime.Mysql.username,
                       'password': Runtime.Mysql.password,
                       'database': Runtime.Mysql.database,
                       'port': Runtime.Mysql.port}
        self.db_config = db_config if db_config else _tmp_config
        self.modified_by = Runtime.User.user

    def execute_query(self, query: str, params: tuple = ()) -> Any:
        try:
            with MysqlAction(**self.db_config) as mysql:
                cursor = mysql.connection.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except MySQLError as e:
            logger.error(f"Error executing query: {e}")
            return []

    def execute_insert(self, query: str, params: tuple = ()) -> int:
        try:
            with MysqlAction(**self.db_config) as mysql:
                cursor = mysql.connection.cursor()
                params_with_modified_by = params + (self.modified_by,)
                cursor.execute(query, params_with_modified_by)
                mysql.connection.commit()
                return cursor.lastrowid
        except MySQLError as e:
            logger.error(f"Error executing insert: {e}")
            return -1

    def execute_update(self, query: str, params: tuple = ()) -> int:
        try:
            with MysqlAction(**self.db_config) as mysql:
                cursor = mysql.connection.cursor()
                current_time = TimeUtils.get_current_datatime()
                params_with_modified_by_and_time = params[:-1] + (current_time, self.modified_by,
                                                                  params[-1])
                print(params_with_modified_by_and_time)
                cursor.execute(query, params_with_modified_by_and_time)
                mysql.connection.commit()
                return cursor.rowcount
        except MySQLError as e:
            logger.error(f"Error executing update: {e}")
            return -1

    def start_transaction(self) -> Connection:
        try:
            mysql = MysqlAction(**self.db_config)
            mysql.connection.start_transaction()
            return mysql.connection
        except MySQLError as e:
            logger.error(f"Error starting transaction: {e}")
            raise

    @staticmethod
    def commit_transaction(connection: Connection):
        try:
            connection.commit()
        except MySQLError as e:
            logger.error(f"Error committing transaction: {e}")
            raise
        finally:
            if connection:
                connection.close()

    @staticmethod
    def rollback_transaction(connection: Connection):
        try:
            connection.rollback()
        except MySQLError as e:
            logger.error(f"Error rolling back transaction: {e}")
            raise

    @staticmethod
    def close_connection(connection: Connection):
        try:
            connection.close()
        except MySQLError as e:
            logger.error(f"Error closing connection: {e}")
            raise

    def execute_with_transaction(self, query: str, params: tuple = (),
                                 connection: Optional[Connection] = None,):
        """
        Execute SQL query with transaction and handle possible exceptions.
        :param query:
        :param params:
        :param connection:
        :return:
        """
        is_new_connection = False
        if connection is None:
            connection = self.start_transaction()
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            result = cursor.lastrowid if (
                query.strip().lower().startswith('insert')) else cursor.rowcount
            # return connection and result if new connection is created
            if is_new_connection:
                return connection, result
            else:
                return None, result
        except MySQLError as e:
            if is_new_connection:
                connection.rollback()
                connection.close()
            logger.error(f"Error in execute_with_transaction: {e}")
            raise




