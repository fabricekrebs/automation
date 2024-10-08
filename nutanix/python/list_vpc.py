#!/usr/bin/env python

import math
import os

from dotenv import load_dotenv
import ntnx_networking_py_client

load_dotenv()

# Customizable variables
pcIp = os.getenv('PRISM_CENTRAL')  # Prism Central IP
username = os.getenv('PC_ADMIN') # Nutanix username
password = os.getenv('PC_PASSWORD')  # Nutanix password

#########################################
#        SDK client configuration
#########################################

# Configure the client
config = ntnx_networking_py_client.Configuration()
config.host = pcIp
config.port = 9440
config.maxRetryAttempts = 3
config.backoffFactor = 3
config.username = username
config.password = password
config.verify_ssl = False
config.debug = True

# Function to check VPC status
def listVPC(timeout=3000, interval=1):
    vpcList = []
    page = 0

    client = ntnx_networking_py_client.ApiClient(configuration=config)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)

    nbPages = 10000
    limitPerPage = 50

    while page < nbPages:
        response = vpcsApi.list_vpcs(_page=page, _limit=limitPerPage)
        myData = response.to_dict()

        nbPages = math.ceil(myData['metadata']['total_available_results'] / limitPerPage)

        for item in myData['data']:
            vpcList.append({'name': item['name'], 'ext_id': item['ext_id']})
        page += 1

    return vpcList

# Main execution
def main():
    vpcList = listVPC()

    for vpc in vpcList:
       print(vpc['name'])

if __name__ == "__main__":
    main()
