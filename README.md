# SaliBot 🤖

SaliBot — ask me anything.

SaliBot is my own ChatGPT-style AI chatbot, named after me (Salima).

## Features
- Chat with an AI assistant
- Simple, friendly interface

## Tech Stack
- Coming soon

# How to run SaliBot

## 1. Clone the repository:
```bash
git clone https://github.com/Iddrisusalima/SaliBot.git
```

## 2. Navigate to the project directory:
```bash
cd SaliBot
```

## 3. Create a virtual environment (optional but recommended):
```bash
conda create -n salibot python=3.11 -y
```

## 4. Activate the virtual environment:
```bash
conda activate salibot
```

## 5. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## 6. Run the application:
```bash
python app.py
```


# AWS-CICD-Deployment-with-Github-Actions

## 1. Login to AWS console.

## 2. Create IAM user for deployment

	#with specific access

	1. EC2 access : It is virtual machine

	2. ECR: Elastic Container registry to save your docker image in aws


	#Description: About the deployment

	1. Build docker image of the source code

	2. Push your docker image to ECR

	3. Launch Your EC2

	4. Pull Your image from ECR in EC2

	5. Lauch your docker image in EC2

	#Policy:

	1. AmazonEC2ContainerRegistryFullAccess

	2. AmazonEC2FullAccess

## 3. Create ECR repo to store/save docker image
Create an Amazon ECR repository named `salibot`.

For GitHub Secrets, save **only the repository name** (not the full URI):
```text
ECR_REPO=salibot
```

## 4. Create EC2 machine (Ubuntu)
Recommended inbound security group rule:
```text
Type: Custom TCP
Port: 8080
Source: 0.0.0.0/0
```

## 5. Open EC2 and install docker in EC2 machine
```bash
sudo apt-get update -y
sudo apt-get upgrade -y
```
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```
```bash
sudo usermod -aG docker ubuntu
newgrp docker
```
```bash
docker --version
```

## 6. Configure EC2 as self-hosted runner
GitHub repo → **Settings → Actions → Runners → New self-hosted runner** → choose **Linux** and run the commands GitHub shows, one by one.

Start the runner:
```bash
./run.sh
```
Or keep it running as a service:
```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

## 7. Setup github secrets
GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**
```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION
ECR_REPO

GOOGLE_API_KEY
GOOGLE_MODEL
TAVILY_API_KEY
LANGSMITH_TRACING
LANGSMITH_ENDPOINT
LANGSMITH_API_KEY
LANGSMITH_PROJECT
```
Example values (the keys themselves stay secret):
```text
AWS_DEFAULT_REGION=us-east-1
ECR_REPO=salibot
GOOGLE_MODEL=gemini-3.5-flash-lite
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=salibot
```

## 8. GitHub Actions workflow
File: `.github/workflows/cicd.yaml`

On every push to `main` it will:
1. Build the Docker image
2. Push the image to Amazon ECR
3. Pull the latest image on EC2
4. Stop the old container
5. Run the new container

## Author
Built by Salima Iddrisu
