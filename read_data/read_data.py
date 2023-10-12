import boto3

AWS_ACCESS_KEY = 'd6f2614d1a84055eb1fa65b50f394cb0'
AWS_SECRET_KEY = 'a1417644adc0d025b325da0fff96a2dc60813545efa44d9c291e14e66e4e441f'
S3_API = 'https://bdadc4417ecd7714dd7d42a104a276c2.r2.cloudflarestorage.com'
BUCKET_NAME = 'data-engineer-test'

s3_client = boto3.resource('s3')
bucket = s3_client.Bucket('data-engineer-test')

for obj in bucket.objects.all():
    key = obj.key


