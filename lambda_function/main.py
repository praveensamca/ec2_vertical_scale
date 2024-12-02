import requests
import json
import boto3 , time
from re import search
import re , os , sys
from datetime import datetime
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

class infra:

    def __init__(self,id="None"):
        self.id=id
        self.sns_client = boto3.client('sns',
                aws_access_key_id=os.getenv("access_key"),
                aws_secret_access_key=os.getenv("secret_key"),
                region_name=os.getenv("region"))
        self.url = "https://local/profile.php"
        self.data = {
            "user_token": "url",
            "editId": "0"
        }
        self.dynamodb_client = boto3.resource('dynamodb',
                aws_access_key_id=os.getenv("access_key"),
                aws_secret_access_key=os.getenv("secret_key"),
                region_name=os.getenv("region"))
        self.s=boto3.client('ec2', 
            aws_access_key_id=os.getenv("access_key"),
            aws_secret_access_key=os.getenv("secret_key"),
            region_name=os.getenv("region"))  
        self.ec2=boto3.resource('ec2',
                aws_access_key_id=os.getenv("access_key"),
                aws_secret_access_key=os.getenv("secret_key"),
                region_name=os.getenv("region"))

    def query_dynamodb(self,table_name, partition_key_name, partition_key_value, sort_key_name=None, sort_key_value=None):
        try:
            # Initialize the DynamoDB client
            
            table = self.dynamodb_client.Table("schedular")
            
            # Build query parameters
            query_params = {
                "KeyConditionExpression": boto3.dynamodb.conditions.Key(partition_key_name).eq(partition_key_value)
            }
            
            # Add sort key condition if provided
            if sort_key_name and sort_key_value:
                query_params["KeyConditionExpression"] &= boto3.dynamodb.conditions.Key(sort_key_name).eq(sort_key_value)
            
            # Execute the query
            response = table.query(**query_params)
            return response['Items'][0]

        except NoCredentialsError:
            print("AWS credentials not found. Please configure your credentials.")
        except PartialCredentialsError:
            print("Incomplete AWS credentials configuration.")
        except Exception as e:
            print(f"An error occurred: {e}")

    def stop(self):
        self.s.stop_instances(InstanceIds=[self.id])

    def start(self):
        self.s.start_instances(InstanceIds=[self.id])

    def state(self):
        for i in self.s.describe_instances()['Reservations']:
            for j in i['Instances']:
                if j['InstanceId'] == self.id:
                    return j['State']['Name']

    def send_email_sns(self,topic_arn, subject, message):
        try:
            response_sms = self.sns_client.publish(
                TopicArn=topic_arn,
                Subject=subject,
                Message=message
            )
        except Exception as e:
            print("Error sending email:", str(e))
    
    def update_table(self,item):
        table = self.dynamodb_client.Table("schedular")
        now = datetime.now()
        if now.hour <= 12:
            topic_arn = os.getenv("topic_arn")
            subject = "Starting instance on m5.2xlarge"
            message = "Starting instance on m5.2xlarge , Please check the url once"
            self.scale(topic_arn, subject, message,os.getenv("regular_size"))
            response = table.put_item(Item=item)
        elif now.hour > 12 and now.hour <24:
            topic_arn = os.getenv("topic_arn")
            subject = "Starting instance on m5.large"
            message = "Starting instance on m5.large , Please check the url once"
            self.scale(topic_arn, subject, message,os.getenv("down_size"))
            response = table.put_item(Item=item)

    def write_dynamo(self,status):
        global timeofday , morning , evening
        now = datetime.now()
        if now.hour < 12:
            timeofday="morning"
        else:
            timeofday="evening"
        item = {
            "status": status, 
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "timeofday": timeofday
            }
        table = self.dynamodb_client.Table("schedular")
        print("Entering service")
        response = table.scan()  # Scan retrieves all items in the table
        items = response.get('Items', [])
        try:
            if now.hour <= 12:
                morning=self.query_dynamodb("schedular","timeofday","morning")
                if morning["day"] == now.day and morning["month"] == now.month:
                    print("morning",morning)
                    print("Already morning exists")
                    return
                else:
                    self.update_table(item)
            elif now.hour > 12 and now.hour <24:
                evening=self.query_dynamodb("schedular","timeofday","evening")
                if evening["day"] == now.day and evening["month"] == now.month:
                    print(evening["day"] , now.day)
                    print("evening",evening)
                    print("Evening already exists")
                    return
                else:
                    self.update_table(item)
            else:
                print("Updating table")
                self.update_table(item)

        except Exception as e:
            print(f"Error reading from DynamoDB {e}")
            self.update_table(item)

    def scale(self,topic_arn, subject, message,size):
        while True:
            if search(r"stopping" ,self.state() , re.I):
                print("Stopping")
            elif search(r"running" ,self.state() , re.I):
                print("Instance is running")
                self.stop()
            elif search(r"stopped" ,self.state() , re.I):
                print(f"Instance is stopped , starting now with new instance type f{size}")
                self.s.modify_instance_attribute(InstanceId=self.id, Attribute='instanceType', Value=size)
                self.start()
                self.send_email_sns(topic_arn, subject, message)
                time.sleep(5)
                while not search(r"running" ,self.state() , re.I):
                    print("Status :",self.state())
                break

    def filter_instance(self):
        instance_list=[]
        filters = [
            {
                'Name': 'tag:instance_type', 
                'Values': ['duplicate']
            }
        ]
        instances = self.ec2.instances.filter(Filters=filters)
        for i in instances:
            instance_list.append(i.id)
        return instance_list

    def validate(self):
        print("inside")
        print(os.getenv("size"))
        try:
            print("Inside try")
            print(requests.post(self.url, json=self.data))
            response = requests.post(self.url, json=self.data)
            print(response)
            # Check if the request was successful
            if response.status_code == 200:
                s=json.loads(response.text)
                if s["status_code"] == 200:
                    topic_arn = os.getenv("topic_arn")
                    subject = "Aplication is up"
                    message = f"Applicaiton is up {response.text}"
                    self.send_email_sns(topic_arn, subject, message)
                else:
                    topic_arn = os.getenv("topic_arn")
                    subject = "Aplication is down"
                    message = f"Applicaiton is down {response.text}"
                    self.send_email_sns(topic_arn, subject, message)
            else:
                print(f"Failed with status code: {response.status_code}")
                print("Response:", response.text)
                topic_arn = os.getenv("topic_arn")
                subject = "Aplication is down"
                message = f"Applicaiton is down {response.text}"
                self.send_email_sns(topic_arn, subject, message)

        except Exception as e:
            print("An error occurred:", str(e))

        s=json.loads(response.text)
        if s["status_code"] == 200:
            topic_arn = os.getenv("topic_arn")
            subject = "Aplication is up"
            message = f"Applicaiton is up {response.text}"
            self.send_email_sns(topic_arn, subject, message)
            return ("Application load successfully")
        else:
            topic_arn = os.getenv("topic_arn")
            subject = "Aplication is down"
            message = f"Applicaiton is down {response.text}"
            self.send_email_sns(topic_arn, subject, message)
            return ("Application load failure")



def lambda_handler(event, context):
    j=infra()
    for j in j.filter_instance():
        date=datetime.now()
        i=infra(j)
        i.write_dynamo(date)
        i.validate()
        

