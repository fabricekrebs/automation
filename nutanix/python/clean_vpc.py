#!/usr/bin/env python

import math
import os
import time

from dotenv import load_dotenv
import ntnx_networking_py_client
import ntnx_vmm_py_client
from ntnx_vmm_py_client.rest import ApiException as VMMException

# Load environment variables
load_dotenv()

# Customizable variables
prismCentralIp = os.getenv('PRISM_CENTRAL')  # Prism Central IP
pcUsername = os.getenv('PC_ADMIN')  # Nutanix username
pcPassword = os.getenv('PC_PASSWORD')  # Nutanix password
vpcName = os.getenv('VPC_NAME')

#########################################
# SDK Client Configuration
#########################################

# Configure the client
sdkConfig = ntnx_networking_py_client.Configuration()
sdkConfig.host = prismCentralIp
sdkConfig.port = 9440
sdkConfig.maxRetryAttempts = 3
sdkConfig.backoffFactor = 3
sdkConfig.username = pcUsername
sdkConfig.password = pcPassword
sdkConfig.verify_ssl = False


# Function to retrieve VPC ID
def getVpcId(vpcName):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)

    for vpc in vpcsApi.list_vpcs().data:
        if vpc.name == vpcName:
            return vpc._ExternalizableAbstractModel__ext_id
    return False


# Function to retrieve subnets in a VPC
def retrieveVpcSubnets(vpcId):
    subnetList = []
    nbPages = 10000
    page = 0
    limitPerPage = 50

    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    subnetApi = ntnx_networking_py_client.SubnetsApi(api_client=client)

    while page < nbPages:
        response = subnetApi.list_subnets(_page=page, _limit=limitPerPage, _filter="vpcReference eq '" + vpcId + "'")
        myData = response.to_dict()

        nbPages = math.ceil(myData['metadata']['total_available_results'] / limitPerPage)

        if myData['data'] is not None:
            for item in myData['data']:
                subnetList.append({'name': item['name'], 'ext_id': item['ext_id']})

        page += 1

    return subnetList


# Function to delete VMs by subnet ID
def deleteVmsBySubnet(networkExtId):
    client = ntnx_vmm_py_client.ApiClient(configuration=sdkConfig)
    vmApi = ntnx_vmm_py_client.VmApi(api_client=client)

    try:
        listVMs = vmApi.list_vms(_filter="nics/any(d:d/networkInfo/subnet/extId eq '%s')" % networkExtId)

        # Delete the VMs in the subnet if they exist
        if listVMs.data is not None:
            for vm in listVMs.data:
                print("The following VM will be deleted: %s" % vm.name)
                etagValue = client.get_etag(vmApi.get_vm_by_ext_id(extId=vm.ext_id))
                vmApi.delete_vm(vm.ext_id, if_match=etagValue)

        # Check every 1 second if all VMs on this subnet are deleted, with a timeout of 60 seconds
        timeout = 60
        start_time = time.time()
        while True:
            listVMs = vmApi.list_vms(_filter="nics/any(d:d/networkInfo/subnet/extId eq '%s')" % networkExtId)
            if not listVMs.data:
                return True
            if time.time() - start_time > timeout:
                return False
            print("Wait for VM deletion")
            time.sleep(1)

    except VMMException as e:
        print(e)


# Function to delete a subnet by its ID
def deleteSubnetById(subnetExtId):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    subnetApi = ntnx_networking_py_client.SubnetsApi(api_client=client)

    try:
        print("The following subnet will be deleted: %s" % subnetExtId)
        subnetApi.delete_subnet_by_id(subnetExtId)
    except ntnx_networking_py_client.rest.ApiException as e:
        print(e)


# Function to delete a VPC by its ID
def deleteVpcById(vpcId):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)

    try:
        print("The following VPC will be deleted: %s" % vpcId)
        vpcsApi.delete_vpc_by_id(vpcId)
    except ntnx_networking_py_client.rest.ApiException as e:
        print(e)


# Main execution function
def main():
    vpcId = getVpcId(vpcName)

    if vpcId != False:
        vpcSubnets = retrieveVpcSubnets(vpcId)

        for subnet in vpcSubnets:
            deleteVmsBySubnet(subnet['ext_id'])
            deleteSubnetById(subnet['ext_id'])

        deleteVpcById(vpcId)

        print("VPC %s has been deleted" % vpcName)


if __name__ == "__main__":
    main()
