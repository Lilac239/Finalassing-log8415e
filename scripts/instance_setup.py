from dotenv import load_dotenv
import os
import boto3
import json

# -----------------------
# Load .env robustly
# -----------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
load_dotenv(ENV_PATH)

region = os.getenv("AWS_DEFAULT_REGION")
key_name = os.getenv("KEY_NAME")

print("Region:", region)
print("Key name:", key_name)

if not region or not key_name:
    raise SystemExit(
        "ERROR: AWS_DEFAULT_REGION or KEY_NAME is missing.\n"
        f"Make sure .env exists here: {ENV_PATH}\n"
        "Example .env:\n"
        "AWS_DEFAULT_REGION=us-east-1\n"
        "KEY_NAME=log8415e-key\n"
    )

ec2 = boto3.client("ec2", region_name=region)

# Default VPC
vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
if not vpcs["Vpcs"]:
    raise SystemExit("ERROR: No default VPC found in this region.")
vpc_id = vpcs["Vpcs"][0]["VpcId"]

# -----------------------
# Security Groups
# -----------------------
def get_or_create_sg(ec2, group_name, description, vpc_id):
    sgs = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [group_name]}, {"Name": "vpc-id", "Values": [vpc_id]}]
    )["SecurityGroups"]
    if sgs:
        return sgs[0]
    resp = ec2.create_security_group(GroupName=group_name, Description=description, VpcId=vpc_id)
    # return same structure as describe
    return ec2.describe_security_groups(GroupIds=[resp["GroupId"]])["SecurityGroups"][0]

gatekeeper_sg = get_or_create_sg(ec2, "gatekeeper-sg", "Public Gatekeeper SG", vpc_id)
cluster_sg = get_or_create_sg(ec2, "cluster-internal-sg", "Internal Cluster SG (Proxy + DBs)", vpc_id)

print("Security Groups Created/Retrieved.")

def rule_exists(existing_perms, new_perm):
    for perm in existing_perms:
        if (perm.get("IpProtocol") == new_perm.get("IpProtocol") and
            perm.get("FromPort") == new_perm.get("FromPort") and
            perm.get("ToPort") == new_perm.get("ToPort")):

            existing_cidrs = {r.get("CidrIp") for r in perm.get("IpRanges", [])}
            new_cidrs = {r.get("CidrIp") for r in new_perm.get("IpRanges", [])}
            existing_groups = {g.get("GroupId") for g in perm.get("UserIdGroupPairs", [])}
            new_groups = {g.get("GroupId") for g in new_perm.get("UserIdGroupPairs", [])}

            if existing_cidrs == new_cidrs and existing_groups == new_groups:
                return True
    return False

def add_ingress_rule_if_not_exists(ec2, sg_id, ip_permissions):
    sg = ec2.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"][0]
    existing_perms = sg["IpPermissions"]

    for perm in ip_permissions:
        if not rule_exists(existing_perms, perm):
            try:
                ec2.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=[perm])
            except Exception as e:
                # ignore duplicate rule errors
                if "InvalidPermission.Duplicate" in str(e):
                    pass
                else:
                    raise

# Gatekeeper: SSH + HTTP
add_ingress_rule_if_not_exists(
    ec2,
    gatekeeper_sg["GroupId"],
    [
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        {"IpProtocol": "tcp", "FromPort": 8080, "ToPort": 8080, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
    ]
)

# Cluster: SSH + all TCP from gatekeeper + all TCP from itself + ICMP inside
add_ingress_rule_if_not_exists(
    ec2,
    cluster_sg["GroupId"],
    [
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        {"IpProtocol": "tcp", "FromPort": 0, "ToPort": 65535, "UserIdGroupPairs": [{"GroupId": gatekeeper_sg["GroupId"]}]},
        {"IpProtocol": "tcp", "FromPort": 0, "ToPort": 65535, "UserIdGroupPairs": [{"GroupId": cluster_sg["GroupId"]}]},
        {"IpProtocol": "icmp", "FromPort": -1, "ToPort": -1, "UserIdGroupPairs": [{"GroupId": cluster_sg["GroupId"]}]}
    ]
)

print("Security Group Rules Configured.")
print("Launching Instances...")

AMI_ID = "ami-0c398cb65a93047f2"  #  must exist in your region

# -----------------------
# Instances (change HERE if prof wants 3 instances)
# -----------------------
PROF_WANTS_3_INSTANCES = False  # <-- set True if needed

gatekeeper = ec2.run_instances(
    ImageId=AMI_ID,
    InstanceType="t2.large",
    KeyName=key_name,
    MinCount=1, MaxCount=1,
    SecurityGroupIds=[gatekeeper_sg["GroupId"]],
    TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "Gatekeeper"}]}]
)

proxy = ec2.run_instances(
    ImageId=AMI_ID,
    InstanceType="t2.large",
    KeyName=key_name,
    MinCount=1, MaxCount=1,
    SecurityGroupIds=[cluster_sg["GroupId"]],
    TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "Proxy"}]}]
)

mysql_manager = ec2.run_instances(
    ImageId=AMI_ID,
    InstanceType="t2.micro",
    KeyName=key_name,
    MinCount=1, MaxCount=1,
    SecurityGroupIds=[cluster_sg["GroupId"]],
    TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "MySQL-Manager"}]}]
)

mysql_workers = {"Instances": []}
if not PROF_WANTS_3_INSTANCES:
    mysql_workers = ec2.run_instances(
        ImageId=AMI_ID,
        InstanceType="t2.micro",
        KeyName=key_name,
        MinCount=2, MaxCount=2,
        SecurityGroupIds=[cluster_sg["GroupId"]],
        TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "MySQL-Worker"}]}]
    )

print("Instances launched. Waiting for running state...")

all_instances = gatekeeper["Instances"] + proxy["Instances"] + mysql_manager["Instances"] + mysql_workers["Instances"]
all_ids = [i["InstanceId"] for i in all_instances]

waiter = ec2.get_waiter("instance_running")
waiter.wait(InstanceIds=all_ids)

desc = ec2.describe_instances(InstanceIds=all_ids)
print("All instances are running.")

cluster_info = {"gatekeeper": {}, "proxy": {}, "manager": {}, "workers": []}

worker_ips = []
manager_ip = None
manager_private_ip = None
gatekeeper_ip = None
proxy_ip = None

for reservation in desc["Reservations"]:
    for instance in reservation["Instances"]:
        name_tag = next((t["Value"] for t in instance.get("Tags", []) if t["Key"] == "Name"), "Unknown")
        private_ip = instance.get("PrivateIpAddress")
        public_ip = instance.get("PublicIpAddress")

        print(f"{name_tag}: Public={public_ip}, Private={private_ip}")
        node_data = {"public_ip": public_ip, "private_ip": private_ip}

        if name_tag == "Gatekeeper":
            cluster_info["gatekeeper"] = node_data
            gatekeeper_ip = public_ip
        elif name_tag == "Proxy":
            cluster_info["proxy"] = node_data
            proxy_ip = public_ip
        elif name_tag == "MySQL-Manager":
            cluster_info["manager"] = node_data
            manager_ip = public_ip
            manager_private_ip = private_ip
        elif name_tag == "MySQL-Worker":
            worker_ips.append(public_ip)
            cluster_info["workers"].append(node_data)

# -----------------------
# Output files (in scripts/)
# -----------------------
out_dir = SCRIPT_DIR  # scripts/
with open(os.path.join(out_dir, "cluster_info.json"), "w", encoding="utf-8") as f:
    json.dump(cluster_info, f, indent=4)

with open(os.path.join(out_dir, "worker_ips.txt"), "w", encoding="utf-8") as f:
    for ip in worker_ips:
        f.write(f"{ip}\n")

with open(os.path.join(out_dir, "manager_ip.txt"), "w", encoding="utf-8") as f:
    f.write(manager_ip or "")

with open(os.path.join(out_dir, "manager_private_ip.txt"), "w", encoding="utf-8") as f:
    f.write(manager_private_ip or "")

with open(os.path.join(out_dir, "gatekeeper_ip.txt"), "w", encoding="utf-8") as f:
    f.write(gatekeeper_ip or "")

with open(os.path.join(out_dir, "proxy_ip.txt"), "w", encoding="utf-8") as f:
    f.write(proxy_ip or "")

print("\nCluster configuration saved to scripts/*.txt and cluster_info.json")
print(json.dumps(cluster_info, indent=4))
