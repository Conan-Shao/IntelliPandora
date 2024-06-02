# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : uuidutils.py
@Time  : 2024-06-02
"""
import uuid


class UUIDFactory:
    @staticmethod
    def generate_uuid1():
        """
        Generate a UUID based on the host ID and current time.
        :return: UUID1 as a string
        """
        return str(uuid.uuid1())

    @staticmethod
    def generate_uuid3(namespace, name):
        """
        Generate a UUID based on the MD5 hash of a namespace UUID and a name.
        :param namespace: The namespace UUID
        :param name: The name (string)
        :return: UUID3 as a string
        """
        return str(uuid.uuid3(namespace, name))

    @staticmethod
    def generate_uuid4():
        """
        Generate a random UUID.
        :return: UUID4 as a string
        """
        return str(uuid.uuid4())

    @staticmethod
    def generate_uuid5(namespace, name):
        """
        Generate a UUID based on the SHA-1 hash of a namespace UUID and a name.
        :param namespace: The namespace UUID
        :param name: The name (string)
        :return: UUID5 as a string
        """
        return str(uuid.uuid5(namespace, name))


if __name__ == "__main__":
    factory = UUIDFactory()

    # UUID1
    print("UUID1:", factory.generate_uuid1())

    # UUID3
    namespace_uuid = uuid.NAMESPACE_DNS
    print("UUID3:", factory.generate_uuid3(namespace_uuid, "example.com"))

    # UUID4
    print("UUID4:", factory.generate_uuid4())

    # UUID5
    print("UUID5:", factory.generate_uuid5(namespace_uuid, "example.com"))

