# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : baserepository.py
@Time  : 2024-05-23
"""
from typing import Any, Optional, Tuple
from pymysql.connections import Connection
from pymysql.err import MySQLError
from ipandora.common.mysqlaction import MysqlAction
from ipandora.common.timeutils import TimeUtils
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.log import logger


class BaseRepository(object):
    def __init__(self, db_config = None):
        _tmp_config = {'host': GTRuntime.Mysql.host,
                       'username': GTRuntime.Mysql.username,
                       'password': GTRuntime.Mysql.password,
                       'database': GTRuntime.Mysql.database,
                       'port': GTRuntime.Mysql.port}
        self.db_config = db_config if db_config else _tmp_config
        self.modified_by = GTRuntime.User.user

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
                cursor.execute(query, params_with_modified_by_and_time)
                mysql.connection.commit()
                return cursor.rowcount
        except MySQLError as e:
            logger.error(f"Error executing update: {e}")
            return -1

    def start_transaction(self) -> Connection:
        """
        Start a transaction and return the connection.
        :return:
        """
        logger.info("Start a transaction.")
        try:
            mysql = MysqlAction(**self.db_config).connect()
            mysql.start_transaction()
            return mysql.connection
        except MySQLError as e:
            logger.error(f"Error starting transaction: {e}")
            raise

    @staticmethod
    def commit_transaction(connection: Connection):
        logger.info("Start to commit transaction.")
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
        """
        Rollback a transaction.
        :param connection:
        :return:
        """
        logger.warning("Start to rollback transaction.")
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
            logger.warning(f"Error closing connection: {e}")

    def execute_with_transaction(self, query: str, params: tuple = (),
                                 connection: Optional[Connection] = None
                                 ) -> Tuple[Optional[Connection], int]:
        """
        Execute SQL query with transaction and handle possible exceptions.
        :param query: SQL query string
        :param params: Parameters to be used in the query
        :param connection: Optional existing connection of database
        :return: Connection and result
        """
        is_new_connection = False
        if connection is None:
            connection = self.start_transaction()
            is_new_connection = True
        try:
            cursor = connection.cursor()

            # Modify params based on query type
            if query.strip().lower().startswith('insert'):
                params_with_modified_by = params + (self.modified_by,)
                cursor.execute(query, params_with_modified_by)
                result = cursor.lastrowid
            elif query.strip().lower().startswith('update'):
                current_time = TimeUtils.get_current_datatime()
                params_with_modified_by_and_time = params[:-1] + (current_time, self.modified_by,
                                                                  params[-1])
                cursor.execute(query, params_with_modified_by_and_time)
                result = cursor.rowcount
            else:
                cursor.execute(query, params)
                result = cursor.rowcount

            # Commit if new connection was created
            if is_new_connection:
                return connection, result
            return None, result
        except MySQLError as e:
            if is_new_connection:
                connection.rollback()
                connection.close()
            logger.error(f"Error in execute_with_transaction: {e}")
            raise

    @staticmethod
    def _get_fields_and_values(obj, operation= "insert", exclude_fields=None):
        exclude_fields = exclude_fields or []
        fields = []
        values = []
        if isinstance(obj, type):
            if "__annotations__" in dir(obj):
                for attr, value in obj.__annotations__.items():
                    if attr not in exclude_fields:
                        fields.append(attr)
        else:
            for attr, value in obj.__dict__.items():
                # Add any other necessary checks or transformations
                if value is not None and attr not in exclude_fields:
                    if operation == "update":
                        fields.append(f"{attr} = %s")
                    elif operation == "insert":
                        fields.append(attr)
                    values.append(value)
        return fields, values

    def generate_insert_query(self, obj, table_name):
        fields, values = self._get_fields_and_values(obj, 'insert')
        query = f"""
            INSERT INTO {table_name} ({', '.join(fields)}, ModifiedBy)
            VALUES ({', '.join(['%s'] * len(values))}, %s)
        """
        return query, values

    def generate_update_query(self, obj, table_name, primary_key_field):
        fields, values = self._get_fields_and_values(obj, 'update',
                                                     exclude_fields=[primary_key_field])
        query = f"""
            UPDATE {table_name}
            SET {', '.join(fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE {primary_key_field} = %s
        """
        # Add the primary key value to the values list
        values.extend([obj.__dict__[primary_key_field]])
        return query, values

    def generate_select_query(self, obj, table_name, primary_key_field=None):
        fields, values = self._get_fields_and_values(obj, 'select', primary_key_field)
        field_str = ', '.join(fields)
        if primary_key_field:
            query = f"""SELECT {field_str} FROM {table_name} WHERE {primary_key_field} = %s"""
        else:
            query = f"""SELECT {field_str} FROM {table_name}"""
        return query


if __name__ == '__main__':
    from ipandora.core.engine.generator.model.data.testcase import TestAttachmentGetter
    resp = BaseRepository().generate_select_query(TestAttachmentGetter,
                                                  'TestCaseAttachments')
    print(resp)




