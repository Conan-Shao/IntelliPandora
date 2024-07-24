# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : baserepository.py
@Time  : 2024-05-23
"""
from dataclasses import fields
from typing import Any, Dict, Tuple, List, Optional, TypeVar, Type
from pymysql.connections import Connection
from pymysql.err import MySQLError
from ipandora.common.mysqlaction import MysqlAction
from ipandora.common.timeutils import TimeUtils
from ipandora.core.schedule.runtime import Runtime
from ipandora.utils.log import logger
T = TypeVar('T')


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
                if query.count('%s') - len(params) == 1:
                    params_with_modified_by = params + (self.modified_by,)
                else:
                    params_with_modified_by = params
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
        _fields = []
        values = []
        if isinstance(obj, type):
            if "__annotations__" in dir(obj):
                for attr, value in obj.__annotations__.items():
                    if attr not in exclude_fields:
                        _fields.append(attr)
        else:
            for attr, value in obj.__dict__.items():
                # Add any other necessary checks or transformations
                if value is not None and attr not in exclude_fields:
                    if operation == "update":
                        _fields.append(f"{attr} = %s")
                    elif operation == "insert":
                        _fields.append(attr)
                    values.append(value)
        return _fields, values

    def generate_insert_query(self, obj, table_name):
        _fields, values = self._get_fields_and_values(obj, 'insert')
        if 'ModifiedBy' not in _fields:
            _fields.append('ModifiedBy')
        query = f"""
            INSERT INTO {table_name} ({', '.join(_fields)})
            VALUES ({', '.join(['%s'] * len(_fields))})
        """
        return query, values

    def generate_update_query(self, obj, table_name, primary_key_field):
        _fields, values = self._get_fields_and_values(obj, 'update',
                                                      exclude_fields=[primary_key_field])
        query = f"""
            UPDATE {table_name}
            SET {', '.join(_fields)}, UpdatedTime = %s, ModifiedBy = %s
            WHERE {primary_key_field} = %s
        """
        # Add the primary key value to the values list
        values.extend([obj.__dict__[primary_key_field]])
        return query, values

    def generate_select_query(self, obj, table_name, primary_key_field=None):
        _fields, values = self._get_fields_and_values(obj, 'select', primary_key_field)
        field_str = ', '.join(_fields)
        query = f"""SELECT {field_str} FROM {table_name} WHERE Status = 1"""
        if primary_key_field:
            query += f""" AND {primary_key_field} = %s"""
        return query

    @staticmethod
    def filter_fields(rows: List[Dict[str, Any]], dataclass_type: Type[T]) -> List[T]:
        dataclass_fields = {field.name for field in fields(dataclass_type)}
        filtered_rows = [{key: value for key, value in row.items() if key in dataclass_fields}
                         for row in rows]
        return [dataclass_type(**row) for row in filtered_rows] if filtered_rows else []

    @staticmethod
    def filter_single(rows: List[Dict[str, Any]], dataclass_type: Type[T]) -> Optional[T]:
        if not rows:
            return None
        dataclass_fields = {field.name for field in fields(dataclass_type)}
        filtered_row = {key: value for key, value in rows[0].items() if key in dataclass_fields}
        return dataclass_type(**filtered_row) if filtered_row else None


if __name__ == '__main__':
    from ipandora.core.engine.generator.model.data.case import AttachmentGetter
    resp = BaseRepository().generate_select_query(AttachmentGetter,
                                                  'TestCaseAttachments')
    print(resp)




