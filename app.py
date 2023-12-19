import os
import requests
from requests.auth import HTTPBasicAuth
import json
from dateutil.parser import isoparse
import time
import csv
import pandas as pd
from operator import itemgetter
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter


JAMF_SERVER_URL = os.environ['JAMF_SERVER_URL']
token = None
expiration_time_token = 0
login_options = {
    "username": os.environ["JAMF_USERNAME"],
    "password": os.environ["JAMF_PASSWORD"],
}


def get_bearer_token(**options: dict):
    global token
    global expiration_time_token
    response = requests.post(
        f"{JAMF_SERVER_URL}/api/v1/auth/token",
        auth=HTTPBasicAuth(options["username"], options["password"]),
    )
    loaded_json = json.loads(response.text)

    token = f"Bearer {loaded_json['token']}"

    expiration_time_token = isoparse(loaded_json["expires"]).timestamp()


def check_token_expiration(expiration_date):
    epoch_now = time.time()
    if expiration_date > epoch_now:
        print(f"Token valid until the following epoch time: {expiration_date}")
        return True
    else:
        print("No valid token available, getting new token")
        get_bearer_token(**login_options)
        return False


def invalidate_token(token: str):
    headers = {"authorization": token}
    response = requests.post(
        f"{JAMF_SERVER_URL}/api/v1/auth/invalidate-token", headers=headers
    )
    if response.status_code == 204:
        print("Token successfully invalidated")
        os.environ["JAMF_TOKEN"] = ""
        return True
    else:
        return False


def get_list_from_csv(path: str):
    list_of_machines = []
    with open(path) as csv_file:
        csv_reader = csv.reader(csv_file, delimiter=",")
        for row in csv_reader:
            list_of_machines.append(row[0])
    return list_of_machines


def get_list_from_txt(path: str):
    list_of_machines = []
    delimeters = ['"', " ", ",", "\n"]
    with open(path) as f:
        contents = f.readlines()
    for machine in contents:
        for delimeter in delimeters:
            if delimeter in machine:
                machine = machine.replace(delimeter, "")
        list_of_machines.append(machine)
    return list_of_machines


def get_list_from_file(path: str, type: str = "csv"):
    if type == "csv":
        return get_list_from_csv(path)
    elif type == "txt":
        return get_list_from_txt(path)
    elif type == "xlsx":
        return get_list_from_excel(path)


def get_list_from_excel(path: str):
    dataframe1 = pd.read_excel(path)
    return dataframe1["ComputerName"].tolist()


def get_machine_info(machine_name: str, token: str):
    headers = {"accept": "application/json", "authorization": token}
    response = requests.get(
        f"{JAMF_SERVER_URL}/JSSResource/computers/name/{machine_name}", headers=headers
    )
    loaded_json = json.loads(response.text)
    general_loaded_json = loaded_json["computer"]["general"]
    return {
        "computer_id": general_loaded_json["id"],
        "computer_name": general_loaded_json["name"],
        "computer_mac_address": general_loaded_json["mac_address"],
        "computer_alt_mac": general_loaded_json["alt_mac_address"],
        "computer_serial": general_loaded_json["serial_number"],
    }


def create_final_list_machines(list_of_machines, token):
    result_machines = []
    for machine in list_of_machines:
        result_machines.append(get_machine_info(machine, token))
    return result_machines


def get_group(group_name: str, token: str):
    group_name = group_name.replace(" ", "%20")
    try:
        url = f"{JAMF_SERVER_URL}/JSSResource/computergroups/name/{group_name}"
        headers = {"accept": "application/json", "authorization": token}
        response = requests.get(url, headers=headers)
        loaded_json = json.loads(response.text)
        return {
            "group_id": loaded_json["computer_group"]["id"],
            "computers_list": loaded_json["computer_group"]["computers"],
        }
    except Exception as e:
        print(e)
        return False


def check_if_group_exists(group_name, token):
    group_name = group_name.replace(" ", "%20")
    try:
        url = f"{JAMF_SERVER_URL}/JSSResource/computergroups/name/{group_name}"
        headers = {"accept": "application/json", "authorization": token}
        response = requests.get(url, headers=headers)
        return response.status_code == 200
    except Exception as e:
        print(e)
        return False


def add_machines_to_group(group_id, list_of_machines, current_computers, token):
    computers_to_push = []
    current_computers = [x["name"] for x in current_computers]
    for machine in list_of_machines:
        if machine["computer_name"] not in current_computers:
            computers_to_push.append(machine)
    if len(computers_to_push) == 0:
        raise Exception(
            "List of macbooks to push is empty, all machines are already in group"
        )
    computers = ""
    for computer in computers_to_push:
        computers += f"""
                        <computer>
                            <id>{computer['computer_id']}</id>
                            <name>{computer['computer_name']}</name>
                            <mac_address>{computer['computer_mac_address']}</mac_address>
                            <alt_mac_address>{computer['computer_alt_mac']}</alt_mac_address>
                            <serial_number>{computer['computer_serial']}</serial_number>
                        </computer>
                            """
    entire_body = f"""
                    <computer_group>
                        <computer_additions>
                            {computers}
                        </computer_additions>
                    </computer_group>
                    """
    headers = {"authorization": token, "Accept": "application/xml"}
    response = requests.put(
        f"{JAMF_SERVER_URL}/JSSResource/computergroups/id/{group_id}",
        data=entire_body,
        headers=headers,
    )
    print(response.status_code)


if __name__ == "__main__":
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "-n",
        "--name",
        help="Name of the existing group in Jamf. Name is case sensitive",
        type=str,
    )
    parser.add_argument(
        "-p",
        "--path",
        default="./list_of_machines.txt",
        type=str,
        help="Path to the file that contains list of machines (it can be csv, txt or xlsx file)",
    )
    parser.add_argument(
        "-t",
        "--type",
        default="txt",
        type=str,
        help="Type of file, it can be csv, txt or xlsx",
    )
    args = vars(parser.parse_args())

    if len(args["name"] == 0 or len(args["path"]) == 0 or len(args["type"]) == 0):
        raise Exception("All parameters are reuired. Please run ")
    get_bearer_token(**login_options)

    if token == None:
        raise Exception("Something went wrong with a token")
    if expiration_time_token == 0:
        raise Exception("Something went wrong with get_bearer_token function")

    if not check_if_group_exists(args["name"], token):
        raise Exception("Group does not exists")

    group_id, computers_list = itemgetter("group_id", "computers_list")(
        get_group(args["name"], token)
    )

    test_list = get_list_from_file(args["path"], args["type"])
    test_list_prod = create_final_list_machines(test_list, token)
    add_machines_to_group(
        group_id,
        test_list_prod,
        computers_list,
        token,
    )
