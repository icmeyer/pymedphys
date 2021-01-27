# Copyright (C) 2021 Derek Lane, Cancer Care Associates
# Copyright (C) 2018 Cancer Care Associates

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from getpass import getpass
from typing import Callable, Optional

from pymedphys._imports import keyring

KEYRING_SCOPE = "PyMedPhys_SQLLogin_Mosaiq"
USERNAME_KEY = "username"
PASSWORD_KEY = "password"


class WrongUsernameOrPassword(ValueError):
    pass


def get_username_and_password_without_prompt_fallback(
    hostname, port=1433, database="MOSAIQ"
):
    storage_name = get_keyring_storage_name(
        hostname=hostname, port=port, database=database
    )
    user = keyring.get_password(storage_name, USERNAME_KEY)
    password = keyring.get_password(storage_name, PASSWORD_KEY)

    return user, password


def get_username_password_with_prompt_fallback(
    hostname,
    port: int = 1433,
    database: str = "MOSAIQ",
    user_input: Callable = input,
    password_input: Callable = getpass,
    output: Callable = print,
    alias: Optional[str] = None,
):
    if alias is None:
        alias = get_keyring_storage_name(
            hostname=hostname, port=port, database=database
        )

    user, password = get_username_and_password_without_prompt_fallback(
        hostname=hostname, port=port, database=database
    )

    if user is None or user == "":
        output(f"Provide a user that only has `db_datareader` access to '{alias}'")
        user = user_input()
        if user == "":
            error_message = "Username should not be blank."
            output(error_message)
            raise ValueError(error_message)

        save_username(user, hostname=hostname, port=port, database=database)

    if password is None:
        output(f"Provide the password for the '{user}' user on '{alias}'")
        password = password_input()

        save_password(password, hostname=hostname, port=port, database=database)

    return user, password


def save_username(
    username: str, hostname: str, port: int = 1433, database: str = "MOSAIQ"
):
    storage_name = get_keyring_storage_name(
        hostname=hostname, port=port, database=database
    )
    keyring.set_password(storage_name, USERNAME_KEY, username)


def save_password(
    password: str, hostname: str, port: int = 1433, database: str = "MOSAIQ"
):
    storage_name = get_keyring_storage_name(
        hostname=hostname, port=port, database=database
    )
    keyring.set_password(storage_name, PASSWORD_KEY, password)


def delete_credentials(hostname: str, port: int = 1433, database: str = "MOSAIQ"):
    storage_name = get_keyring_storage_name(
        hostname=hostname, port=port, database=database
    )
    keyring.delete_password(storage_name, USERNAME_KEY)
    keyring.delete_password(storage_name, PASSWORD_KEY)


def get_keyring_storage_name(hostname, port=1433, database="MOSAIQ"):
    """returns the storage name for a given DB server + port + name

    Parameters
    ----------
    hostname : str
        db server name
    port : int, optional
        db server port, by default 1433
    database : str, optional
        db name, by default "MOSAIQ"

    Returns
    -------
    str
        the storage name to be used with keyring
    """
    return f"{KEYRING_SCOPE}_{hostname}:{port}/{database}"
