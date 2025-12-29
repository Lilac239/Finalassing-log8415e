# FinalAssignment

1) To use this you have to create a .env at the root with the following fields:
```
AWS_ACCESS_KEY_ID=""
AWS_SECRET_ACCESS_KEY=""
AWS_SESSION_TOKEN=""         
AWS_DEFAULT_REGION="us-east-1"
KEY_NAME="log8415e-key"
```

2) Install requirements:
* pip install -U pip
* pip install -r requirements.txt

3) Create log8415e-key.pem and place it in the scripts folder

4) Run in this order
* `bash scripts/run_demo.sh` to launch instances and run benchmark

5) Clean the demo (recommended):
* `bash scripts/clean_demo.sh`

