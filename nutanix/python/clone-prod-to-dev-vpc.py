#!/usr/bin/env python

import time
import json
import requests
import urllib3
import sys
import re
import math
import os

from dotenv import load_dotenv
import ntnx_networking_py_client, ntnx_vmm_py_client, ntnx_prism_py_client
import ntnx_networking_py_client.models.common.v1.config as v1CommonConfig
import ntnx_networking_py_client.models.networking.v4.config as v4NetConfig
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.CloneOverrideParams import CloneOverrideParams
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.Nic import Nic
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.NicNetworkInfo import NicNetworkInfo
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.SubnetReference import SubnetReference
from ntnx_prism_py_client import Configuration as PrismConfiguration
from ntnx_prism_py_client import ApiClient as PrismClient
from ntnx_prism_py_client.rest import ApiException as PrismException
from ntnx_vmm_py_client import ApiClient as VMMClient
from ntnx_vmm_py_client.rest import ApiException as VMMException

load_dotenv()

# Customizable variables
pcIp = os.getenv('PRISM_CENTRAL')  # Prism Central IP
username = os.getenv('PC_ADMIN') # Nutanix username
password = os.getenv('PC_PASSWORD')  # Nutanix password
vpcName = "vpc-01"
vpcDescription = "This is my VPC description"
vpcType = "REGULAR"  # Can be "REGULAR" or "TRANSIT"
subnetList = {
    "network1": {
        "subnetName": "vpc-01-subnet-01",
        "subnetDescription": "This is the first overlay subnet",
        "ipNetwork": "10.1.0.0",
        "ipPrefix": 24,
        "ipGateway": "10.1.0.1",
        "ipPoolStart": "10.1.0.100",
        "ipPoolEnd": "10.1.0.199"
    },
    "network2": {
        "subnetName": "vpc-01-subnet-02",
        "subnetDescription": "This is the second overlay subnet",
        "ipNetwork": "10.2.0.0",
        "ipPrefix": 24,
        "ipGateway": "10.2.0.1",
        "ipPoolStart": "10.2.0.100",
        "ipPoolEnd": "10.2.0.199"
    }
}

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

# Function to create VPC
def createVpc(vpcName):
    client = ntnx_networking_py_client.ApiClient(configuration=config)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)
    vpc = ntnx_networking_py_client.Vpc()
    vpc.name = vpcName  # required field

    try:
        apiResponse = vpcsApi.create_vpc(body=vpc)
        return True
    except ntnx_networking_py_client.rest.ApiException as e:
        return False

# Check if 'name' field contains 'dev1-vpc'
def checkVpcExists(vpcData, vpcName):
    for vpc in vpcData:
        if vpc.name == vpcName:
            return vpc._ExternalizableAbstractModel__ext_id
    return False

# Function to check VPC status
def waitForVpcCreation(vpcName, timeout=3000, interval=1):
    client = ntnx_networking_py_client.ApiClient(configuration=config)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)
    vpcs = vpcsApi.list_vpcs()

    elapsedTime = 0
    while elapsedTime < timeout:
        vpcId = checkVpcExists(vpcs.data, vpcName)
        if vpcId:
            return vpcId
        else:
            time.sleep(interval)
            elapsedTime += interval

    return False

# Function to create overlay subnet
def createOverlaySubnet(vpcId, subnetName, ipNetwork, ipPrefix, ipGateway, ipPoolStart, ipPoolEnd):
    client = ntnx_networking_py_client.ApiClient(configuration=config)
    subnetsApi = ntnx_networking_py_client.SubnetsApi(api_client=client)
    subnet = ntnx_networking_py_client.Subnet()

    subnet.name = subnetName
    subnet.subnet_type = ntnx_networking_py_client.SubnetType.OVERLAY  # required field
    subnet.vpc_reference = vpcId

    subnet.ip_config = [
        v4NetConfig.IPConfig.IPConfig(
            ipv4=v4NetConfig.IPv4Config.IPv4Config(
                default_gateway_ip=v1CommonConfig.IPv4Address.IPv4Address(
                    prefix_length=ipPrefix,
                    value=ipGateway,
                ),
                ip_subnet=v4NetConfig.IPv4Subnet.IPv4Subnet(
                    ip=v1CommonConfig.IPv4Address.IPv4Address(
                        prefix_length=ipPrefix,
                        value=ipNetwork,
                    ),
                    prefix_length=ipPrefix,
                ),
                pool_list=[
                    v4NetConfig.IPv4Pool.IPv4Pool(
                        start_ip=v1CommonConfig.IPv4Address.IPv4Address(
                            prefix_length=ipPrefix,
                            value=ipPoolStart,
                        ),
                        end_ip=v1CommonConfig.IPv4Address.IPv4Address(
                            prefix_length=ipPrefix,
                            value=ipPoolEnd,
                        )
                    )
                ],
            )
        )
    ]

    try:
        apiResponse = subnetsApi.create_subnet(body=subnet)
    except ntnx_networking_py_client.rest.ApiException as e:
        print(e)

# Function to check VPC status
def retrieveVPCSubnet(vpcId, timeout=3000, interval=1):
    subnetList = []
    nbPages = 10000
    page = 0
    limitPerPage = 50

    client = ntnx_networking_py_client.ApiClient(configuration=config)
    subnetApi = ntnx_networking_py_client.SubnetsApi(api_client=client)

    while page < nbPages:
        response = subnetApi.list_subnets(_page=page, _limit=limitPerPage, _filter="vpcReference eq '" + vpcId + "'")
        myData = response.to_dict()

        nbPages = math.ceil(myData['metadata']['total_available_results'] / limitPerPage)

        for item in myData['data']:
            with open('output.txt', 'a') as file:
                file.write("Subnet Name : " + str(item['name']) + "\n")  # Write data to the file
            subnetList.append({'name': item['name'], 'ext_id': item['ext_id']})
        page += 1

    return subnetList


def getVmByCategories(categoryName, categoryValue):
    vmList = []
    nbPages = 10000
    page = 0
    limitPerPage = 50

    client = ntnx_vmm_py_client.ApiClient(configuration=config)
    vmApi = ntnx_vmm_py_client.VmApi(api_client=client)

    categoryId = getCategoryId(categoryName, categoryValue)

    while page < nbPages:
        # Temporary filter only on VM starting with 'hol' to bypass the uefi issue
        response = vmApi.list_vms(_page=page, _limit=limitPerPage, _orderby="name asc", _filter="startswith(name, 'hol')")
        myData = response.to_dict()

        nbPages = math.ceil(myData['metadata']['total_available_results'] / limitPerPage)

        for item in myData['data']:
            with open('output.txt', 'a') as file:
                file.write("VM Name : " + str(item['name']) + "\n")  # Write data to the file
            if item.get('categories') is not None:
                for category in item['categories']:
                    if category['ext_id'] == categoryId:
                        vmList.append({'name': item['name'], 'ext_id': item['ext_id']})
        page += 1

    return vmList

def getCategoryId(name, value):
    page = 0
    limitPerPage = 50

    client = ntnx_prism_py_client.ApiClient(configuration=config)
    categoriesApi = ntnx_prism_py_client.CategoriesApi(api_client=client)

    try:
        apiResponse = categoriesApi.get_all_categories(_page=page, _limit=limitPerPage, _filter="((value eq '"+value+"') and (key eq '"+name+"'))")
        return apiResponse.to_dict()['data'][0]['ext_id']
    except ntnx_prism_py_client.rest.ApiException as e:
        print(e)

def cloneVMById(vmId, networkExtId, vmName):
    client = ntnx_vmm_py_client.ApiClient(configuration=config)
    vmApi = ntnx_vmm_py_client.VmApi(api_client=client)

    try:
        # Retrieve the VM
        vm = vmApi.get_vm_by_ext_id(extId=vmId)
        etagValue = client.get_etag(vm)

        # Define the NIC
        nics = [
            Nic(
                network_info=NicNetworkInfo(
                    subnet=SubnetReference(ext_id=networkExtId)
                    )
                )
            ]

        cloneConfig = CloneOverrideParams(
            name=vmName,
            nics=nics,
        )
        
        response = vmApi.clone_vm(extId=vmId, body=cloneConfig, if_match=etagValue)
    except VMMException as e:
        print(e)

# Main execution
def main():
    createVpc(vpcName)
    vpcId = waitForVpcCreation(vpcName)

    # Create the VPC network
    for key, value in subnetList.items():
        createOverlaySubnet(
            vpcId, 
            value['subnetName'], 
            value['ipNetwork'], 
            value['ipPrefix'], 
            value['ipGateway'], 
            value['ipPoolStart'], 
            value['ipPoolEnd']
        )

    vmList = getVmByCategories("hol-environment","prod")
    
    vpcSubnets = retrieveVPCSubnet(vpcId)

    for vms in vmList:
       cloneVMById(vms['ext_id'], vpcSubnets[1]['ext_id'], "clone-" + vms['name'])

if __name__ == "__main__":
    main()
