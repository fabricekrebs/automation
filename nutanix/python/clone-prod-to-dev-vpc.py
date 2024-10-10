#!/usr/bin/env python

import os
import time
import math

from dotenv import load_dotenv
import ntnx_networking_py_client
import ntnx_vmm_py_client
import ntnx_prism_py_client
import ntnx_networking_py_client.models
import ntnx_networking_py_client.models.networking
import ntnx_networking_py_client.models.common.v1.config as v1CommonConfig
import ntnx_networking_py_client.models.networking.v4.config as v4NetConfig
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.CloneOverrideParams import CloneOverrideParams
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.Nic import Nic
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.NicNetworkInfo import NicNetworkInfo
from ntnx_vmm_py_client.models.vmm.v4.ahv.config.SubnetReference import SubnetReference
from ntnx_vmm_py_client.rest import ApiException as VMMException

# Load environment variables
load_dotenv()

# Customizable variables
prismCentralIp = os.getenv('PRISM_CENTRAL')  # Prism Central IP
pcUsername = os.getenv('PC_ADMIN')  # Nutanix username
pcPassword = os.getenv('PC_PASSWORD')  # Nutanix password
vpcName = os.getenv('VPC_NAME')
categoryName = os.getenv('CATEGORY_NAME')
categoryValue = os.getenv('CATEGORY_VALUE')
externalNetworkName = os.getenv('EXTERNAL_NETWORK_NAME')
categoryFloatingIPName = os.getenv('CATEGORY_FLOATING_IP_NAME')

# Retry parameters
max_wait_time = 60  # maximum wait time in seconds
interval = 1        # interval between retries in seconds

# Subnet configuration
subnetList = {
    "vpc-01-subnet-01": {
        "subnetDescription": "This is the first overlay subnet",
        "ipNetwork": "172.24.0.0",
        "ipPrefix": 16,
        "ipGateway": "172.24.0.1",
        "ipPoolStart": "172.24.32.10",
        "ipPoolEnd": "172.24.47.254"
    },
    "vpc-01-subnet-02": {
        "subnetDescription": "This is the second overlay subnet",
        "ipNetwork": "10.2.0.0",
        "ipPrefix": 24,
        "ipGateway": "10.2.0.1",
        "ipPoolStart": "10.2.0.100",
        "ipPoolEnd": "10.2.0.199"
    }
}

networkMapping = [
    {"networkName": "IPAM-NXCLUSTER03", "subnetName": "vpc-01-subnet-01"},
    {"networkName": "INFRA", "subnetName": "vpc-01-subnet-02"}
]

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

# Function to create a VPC
def createVpc(vpcName):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    vpcsApi = ntnx_networking_py_client.VpcsApi(api_client=client)
    vpc = ntnx_networking_py_client.Vpc()
    externalSubnet = ntnx_networking_py_client.ExternalSubnet()
    externalSubnet.subnet_reference = retrieveNetworkId(externalNetworkName)
    vpc.name = vpcName  # Required field
    vpc.external_subnets = [externalSubnet]

    try:
        vpcsApi.create_vpc(body=vpc)
        return True
    except ntnx_networking_py_client.rest.ApiException as e:
        return False

# Function to check if a VPC exists
def checkVpcExists(vpcData, vpcName):
    for vpc in vpcData:
        if vpc.name == vpcName:
            return vpc._ExternalizableAbstractModel__ext_id
    return False

# Function to wait for VPC creation
def waitForVpcCreation(vpcName, timeout=3000, interval=1):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
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

# Function to create an overlay subnet
def createOverlaySubnet(vpcId, subnetName, ipNetwork, ipPrefix, ipGateway, ipPoolStart, ipPoolEnd):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    subnetsApi = ntnx_networking_py_client.SubnetsApi(api_client=client)
    subnet = ntnx_networking_py_client.Subnet()

    # Set up the subnet configuration
    subnet.name = subnetName
    subnet.subnet_type = ntnx_networking_py_client.SubnetType.OVERLAY  # Required field
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
        subnetsApi.create_subnet(body=subnet)
    except ntnx_networking_py_client.rest.ApiException as e:
        print(e)

# Function to retrieve subnets in a VPC
def retrieveVpcSubnets(vpcId, timeout=3000, interval=1):
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

        for item in myData['data']:
            subnetList.append({'name': item['name'], 'ext_id': item['ext_id']})
        page += 1

    return subnetList

# Function to retrieve the extId of a specific subnet
def retrieveNetworkId(networkName):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    subnetApi = ntnx_networking_py_client.SubnetsApi(api_client=client)

    response = subnetApi.list_subnets(_filter="name eq '" + str(networkName) + "'")
    myData = response.to_dict()

    if myData['data']:
        return myData['data'][0]['ext_id']
    else:
        return None

# Function to get VMs by categories
def getVmsByCategories(categoryName, categoryValue):
    vmList = []
    nbPages = 10000
    page = 0
    limitPerPage = 50

    client = ntnx_vmm_py_client.ApiClient(configuration=sdkConfig)
    vmApi = ntnx_vmm_py_client.VmApi(api_client=client)

    categoryId = getCategoryId(categoryName, categoryValue)

    while page < nbPages:
        # Temporary filter only on VM starting with 'hol' to bypass the UEFI issue
        response = vmApi.list_vms(_page=page, _limit=limitPerPage, _orderby="name asc", _filter="startswith(name, 'hol')")
        myData = response.to_dict()

        nbPages = math.ceil(myData['metadata']['total_available_results'] / limitPerPage)

        for item in myData['data']:
            if item.get('categories') is not None:
                for category in item['categories']:
                    if category['ext_id'] == categoryId:
                        vmList.append({'name': item['name'], 'ext_id': item['ext_id']})
        page += 1

    return vmList

# Function to get category ID by name and value
def getCategoryId(name, value):
    page = 0
    limitPerPage = 50

    client = ntnx_prism_py_client.ApiClient(configuration=sdkConfig)
    categoriesApi = ntnx_prism_py_client.CategoriesApi(api_client=client)

    try:
        apiResponse = categoriesApi.get_all_categories(_page=page, _limit=limitPerPage, _filter="((value eq '"+value+"') and (key eq '"+name+"'))")
        return apiResponse.to_dict()['data'][0]['ext_id']
    except ntnx_prism_py_client.rest.ApiException as e:
        print(e)

# Function to clone a VM by its ID
def cloneVmById(vmId, networkExtId, vmName):
    client = ntnx_vmm_py_client.ApiClient(configuration=sdkConfig)
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

        vmApi.clone_vm(extId=vmId, body=cloneConfig, if_match=etagValue)
        
        #retrieve the category ID matching
        categoryFloatingIPExtId = getCategoryId(categoryFloatingIPName, 'yes')

        elapsed_time = 0    # time elapsed since the start of the retries

        while elapsed_time < max_wait_time:
            if vmApi.list_vms(_filter="name eq '" + vmName + "'").data is not None:
                break

            print("waiting for VM to be created to assign floating IP")

            # Wait for the specified interval before retrying
            time.sleep(interval)
            elapsed_time += interval  # Update the elapsed time
            

        #check if source VM has the floating IP category
        if vm.data.categories is not None:
            for category in vm.data.categories:
                if category.ext_id == categoryFloatingIPExtId:
                    print("Assigning floating IP to VM")
                    assignFloatingIp(vmName)

    except VMMException as e:
        print(e)

# Function to create a default route
def createDefaultRoute(vpcId):
    externalNetworkId = retrieveNetworkId(externalNetworkName)

    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    routeApi = ntnx_networking_py_client.RouteTablesApi(api_client=client)

    routeTableResponse = routeApi.list_route_tables(_filter="vpcReference eq '" + vpcId + "'")
    routeTableId = routeTableResponse.data[0].ext_id  # Access the ext_id correctly

    # Fetch the full routeTable object by its ID
    routeTable = routeApi.get_route_table_by_id(routeTableId).data
    etagValue = client.get_etag(routeTable)

    # Create a new route
    new_route = v4NetConfig.Route.Route(
        is_active=True,
        priority=32768,
        destination=v4NetConfig.IPSubnet.IPSubnet(
           ipv4=v4NetConfig.IPv4Subnet.IPv4Subnet(
                ip=v1CommonConfig.IPv4Address.IPv4Address(
                    prefix_length=24,
                    value="0.0.0.0",
                ),
                prefix_length=24
            )
        ),
        nexthop_type="EXTERNAL_SUBNET",
        nexthop_reference=externalNetworkId,
        nexthop_ip_address=None,
        nexthop_name=externalNetworkName
    )

    # Check if static_routes exist and append the new route
    if hasattr(routeTable, 'static_routes') and routeTable.static_routes:
        routeTable.static_routes.append(new_route)
    else:
        routeTable.static_routes = [new_route]  # Initialize if empty

    routeApi.update_route_table_by_id(routeTable.ext_id, body=routeTable, if_match=etagValue)

# Function to create a floating IP
def assignFloatingIp(name):
    client = ntnx_networking_py_client.ApiClient(configuration=sdkConfig)
    floatingIpApi = ntnx_networking_py_client.FloatingIpsApi(api_client=client)

    client = ntnx_vmm_py_client.ApiClient(configuration=sdkConfig)
    vmApi = ntnx_vmm_py_client.VmApi(api_client=client)


    floatingIpConfig = v4NetConfig.FloatingIp.FloatingIp()
    vmNicAssociation = v4NetConfig.VmNicAssociation.VmNicAssociation()

    elapsed_time = 0    # time elapsed since the start of the retries
    while elapsed_time < max_wait_time:
        if vmApi.list_vms(_filter="name eq '" + name + "'").data is not None:

            vmNicAssociation.vm_nic_reference = vmApi.list_vms(_filter="name eq '" + name + "'").data[0].nics[0].ext_id
            break

        print("waiting for VM to be created to assign floating IP")

        # Wait for the specified interval before retrying
        time.sleep(interval)
        elapsed_time += interval  # Update the elapsed time

    floatingIpConfig.name = name
    floatingIpConfig.external_subnet_reference = retrieveNetworkId(externalNetworkName)
    floatingIpConfig.association = vmNicAssociation

    try:
        floatingIpApi.create_floating_ip(body=floatingIpConfig)
    except ntnx_networking_py_client.rest.ApiException as e:
        print(e)

# Main execution function
def main():
    createVpc(vpcName)
    vpcId = waitForVpcCreation(vpcName)

    # Create the VPC network
    for key, value in subnetList.items():
        createOverlaySubnet(
            vpcId,
            key,
            value['ipNetwork'],
            value['ipPrefix'],
            value['ipGateway'],
            value['ipPoolStart'],
            value['ipPoolEnd']
        )

    vmList = getVmsByCategories(categoryName, categoryValue)
    
    vpcSubnets = retrieveVpcSubnets(vpcId)

    for vm in vmList:
        cloneVmById(vm['ext_id'], vpcSubnets[1]['ext_id'], "clone-" + vm['name'])

    createDefaultRoute(vpcId)

    print("%s VMs have been cloned" % len(vmList))

if __name__ == "__main__":
    main()
