from dotenv import load_dotenv
import os
import boto3

load_dotenv(".env")

region = os.getenv("AWS_DEFAULT_REGION")
key_name = os.getenv("KEY_NAME")

print("Region:", region)
print("Key name:", key_name)

ec2 = boto3.client("ec2", region_name=region)

print("Fetching instances...")

instances = ec2.describe_instances(
    Filters=[
        {"Name": "tag:Name", "Values": ["Gatekeeper", "Proxy", "MySQL-Manager", "MySQL-Worker"]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}
    ]
)

instance_ids = []
for reservation in instances["Reservations"]:
    for instance in reservation["Instances"]:
        instance_ids.append(instance["InstanceId"])

if instance_ids:
    print(f"Terminating instances: {instance_ids}")
    ec2.terminate_instances(InstanceIds=instance_ids)
    print("Waiting for instances to terminate...")
    waiter = ec2.get_waiter("instance_terminated")
    waiter.wait(InstanceIds=instance_ids)
    print("Instances terminated.")
else:
    print("No Cluster instances found.")

def delete_sg_if_exists(group_name):
    try:
        sgs = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [group_name]}])["SecurityGroups"]
    except Exception as e:
        print(f"Error describing group {group_name}: {e}")
        return

    if not sgs:
        print(f"No security group named '{group_name}' found.")
        return

    for sg in sgs:
        sg_id = sg["GroupId"]
        try:
            print(f"Deleting security group: {group_name} ({sg_id})...")
            ec2.delete_security_group(GroupId=sg_id)
            print(f"Successfully deleted {group_name}")
        except Exception as e:
            print(f"Could not delete {group_name} ({sg_id}): {e}")

delete_sg_if_exists("cluster-internal-sg")
delete_sg_if_exists("gatekeeper-sg")

print("Cleanup complete.")