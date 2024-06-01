# -*- coding: utf-8 -*-
"""
@Author: Shao Feng
@File  : stringaction.py
@Time  : 2024-05-15
"""
import ast
import base64
import json
import re


class StringAction(object):
    @staticmethod
    def contains_chinese(text):
        """
        Check whether the string contains Chinese characters
        :param text:
        :return:
        """
        for char in text:
            if '\u4e00' <= char <= '\u9fff':
                return True
        return False

    @staticmethod
    def to_repr(text):
        """
        Converts a string to its representation and removes single quotes
        :param text:
        :return:
        """
        return repr(text).strip("'")

    @staticmethod
    def to_repr_without_quotes(text):
        """
        Converts a string to its representation and removes all single quotes
        :param text:
        :return:
        """
        return repr(text).replace("'", "")

    @staticmethod
    def format_with_escape_characters(text):
        """
        handle escape characters
        :param text:
        :return:
        """
        parsed_string = ast.literal_eval(repr(text))
        return json.dumps(parsed_string, ensure_ascii=False)[1:-1]

    @staticmethod
    def strip_whitespace(text):
        """
        Removes whitespace at both ends of the string
        :param text:
        :return:
        """
        return text.strip()

    @staticmethod
    def remove_all_whitespace(text):
        """
        Remove all whitespace characters from the string
        :param text:
        :return:
        """
        return re.sub(r'\s+', '', text)

    @staticmethod
    def to_uppercase(text):
        """
        Converts a string to uppercase
        :param text:
        :return:
        """
        return text.upper()

    @staticmethod
    def to_lowercase(text):
        """
        Converts a string to lowercase
        :param text:
        :return:
        """
        return text.lower()

    @staticmethod
    def capitalize_first_letter(text):
        """
        Converts the first letter of a string to uppercase
        :param text:
        :return:
        """
        return text.capitalize()

    @staticmethod
    def contains_substring(text, substring):
        """
        Check whether the string contains substrings
        :param text:
        :param substring:
        :return:
        """
        return substring in text

    @staticmethod
    def replace_substring(text, old, new):
        """
        Replaces a substring in a string
        :param text:
        :param old:
        :param new:
        :return:
        """
        return text.replace(old, new)

    @staticmethod
    def is_base64_encoded(text):
        """
        Check if the string is base64 encoded
        :param text:
        :return:
        """
        if len(text) % 4 != 0:
            return False
        if re.match('^[A-Za-z0-9+/]*={0,2}$', text) is None:
            return False
        try:
            base64.b64decode(text)
            return True
        except Exception:
            return False

    @staticmethod
    def is_aes_encrypted_string(ciphertext):
        # check if the string is base64 encoded
        if not StringAction.is_base64_encoded(ciphertext):
            return False
        # check the length of the decoded data
        decoded_data = base64.b64decode(ciphertext)
        if len(decoded_data) % 16 != 0:
            return False
        return True


if __name__ == '__main__':
    result = StringAction.is_aes_encrypted_string("IvDxMPS+BjIozlMICPmPrSqwcjEM7NhLJXcrt2ChyMc=")
    print(result)
