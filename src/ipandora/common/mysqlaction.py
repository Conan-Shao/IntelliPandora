# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : mysqlaction.py
@Time  : 2024-05-02
"""
import pymysql
import pymysql.cursors
from pymysql.err import MySQLError
from ipandora.utils.log import logger


class MysqlAction(object):
    def __init__(self, host, username, password, database, port = 3306):
        self.connection = None
        self.host = host
        self.user = username
        self.password = password
        self.database = database
        self.port = port

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self):
        """
        Connect to MySQL database, only connect if there is no active connection.
        :return:
        """
        if self.connection is not None:
            logger.warn("Connection already established.")
            return self.connection
        else:
            try:
                self.connection = pymysql.connect(
                    host=self.host,
                    user=self.user,
                    password=self.password,
                    database=self.database,
                    cursorclass=pymysql.cursors.DictCursor
                )
                logger.info("Database connection established.")
                return self
            except MySQLError as e:
                raise MySQLError(f"Error connecting to MySQL Platform: {e}")

    def execute_query(self, query):
        """
        Execute SQL query and handle possible exceptions.
        :param query:
        :return:
        """
        if self.connection is None:
            logger.warn("No connection to the database.")
            return []
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query)
                return cursor.fetchall()
        except MySQLError as e:
            logger.warn(f"Error executing query: {e}")
            return []

    def execute_update(self, query):
        """
        Execute update statements, using transactions.
        :param query:
        :return:
        """
        if self.connection is None:
            logger.warn("No connection to the database.")
            return
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query)
                affected_rows = cursor.rowcount
                self.connection.commit()
                logger.info(f"Transaction committed. {affected_rows} rows affected.")
                return affected_rows
        except MySQLError as e:
            logger.warn(f"Error during transaction, rolling back: {e}")
            self.connection.rollback()

    def close(self):
        """
        close the database connection.
        :return:
        """
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("Database connection closed.")
        else:
            logger.info("No connection to close.")
