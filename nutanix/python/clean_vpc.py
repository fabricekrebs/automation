#!/usr/bin/env python

import math
import os

from dotenv import load_dotenv
import ntnx_networking_py_client, ntnx_vmm_py_client
from ntnx_vmm_py_client.rest import ApiException as VMMException

load_dotenv()

# Customizable variables
pcIp = os.getenv('PRISM_CENTRAL')  # Prism Central IP
username = os.getenv('PC_ADMIN') # Nutanix username
password = os.getenv('PC_PASSWORD')  # Nutanix password
vpcName = os.getenv('VPC_NAME')


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


# Function to check VPC status
def getVPCId(vpcName):
    client = ntnx_networking_py_client.ApiClient(configuration=config)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)

    for vpc in vpcsApi.list_vpcs().data:
        if vpc.name == vpcName:
            return vpc._ExternalizableAbstractModel__ext_id
    return False

# Function to check VPC status
def retrieveVPCSubnet(vpcId):
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


        if myData['data'] is not None:
            for item in myData['data']:
                subnetList.append({'name': item['name'], 'ext_id': item['ext_id']})
        
        page += 1

    return subnetList

def deleteVMBySubnet(networkExtId):
    client = ntnx_vmm_py_client.ApiClient(configuration=config)
    vmApi = ntnx_vmm_py_client.VmApi(api_client=client)

    try:
        listVMs = vmApi.list_vms(_filter="nics/any(d:d/networkInfo/subnet/extId eq '%s')" % networkExtId)

        #delete the VMs in the subnet if it exists
        if listVMs.data is not None:
            for vm in listVMs.data:
                print("The following VM will be deleted: %s" % vm.name)
                etagValue = client.get_etag(vmApi.get_vm_by_ext_id(extId=vm.ext_id))
                vmApi.delete_vm(vm.ext_id, if_match=etagValue)
    except VMMException as e:
        print(e)

def deleteSubnetById(subnetExtId):
    client = ntnx_networking_py_client.ApiClient(configuration=config)
    subnetApi = ntnx_networking_py_client.SubnetsApi(api_client=client)

    try:
        print("The following subnet will be deleted: %s" % subnetExtId)
        subnetApi.delete_subnet_by_id(subnetExtId)
    except ntnx_networking_py_client.rest.ApiException as e:
        print(e)

def deleteVPCById(vpcId):
    client = ntnx_networking_py_client.ApiClient(configuration=config)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)

    try:
        print("The following VPC will be deleted: %s" % vpcId)
        vpcsApi.delete_vpc_by_id(vpcId)
    except ntnx_networking_py_client.rest.ApiException as e:
        print(e)

# Main execution
def main():
    vpcId = getVPCId(vpcName)

    if(vpcId != False):
        vpcSubnets = retrieveVPCSubnet(vpcId)

        for subnet in vpcSubnets:
            deleteVMBySubnet(subnet['ext_id'])
            deleteSubnetById(subnet['ext_id'])

        deleteVPCById(vpcId)

if __name__ == "__main__":
    main()
