# ===================================================================
#               Quant Competition - Add Participant Script
# ===================================================================
# This script automates creating a new participant:
# 1. Generates a random Participant ID.
# 2. Creates an IAM user.
# 3. Creates and attaches a restrictive S3 policy for that user.
# 4. Generates AWS access keys.
# 5. Outputs the .env file contents.
# ===================================================================

# --- CONFIGURATION (UPDATE THESE) ---
$SubmissionsBucket = "comp-submission-bucket"
$AwsRegion = "eu-central-1"
# ------------------------------------

# 1. Generate a random Participant ID
$RandomString = -join (Get-Random -Count 8 -InputObject ([char[]]([char]'a'..[char]'z' + [char]'0'..[char]'9')))
$ParticipantId = "participant-$RandomString"
$UserName = "quant-comp-user-$ParticipantId"
$PolicyName = "QuantCompPolicy-$ParticipantId"

Write-Host "Creating new participant: $ParticipantId" -ForegroundColor Cyan

# 2. Create the IAM user
Write-Host "Creating IAM user: $UserName"
aws iam create-user --user-name $UserName

If (-Not $?) { Write-Error "Failed to create IAM user. Aborting."; return }

# 3. Create the S3 policy
$PolicyDocument = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::$SubmissionsBucket/$ParticipantId/*"
    }
  ]
}
"@

Write-Host "Creating IAM policy: $PolicyName"
$PolicyArn = aws iam create-policy `
    --policy-name $PolicyName `
    --policy-document $PolicyDocument | ConvertFrom-Json | Select-Object -ExpandProperty Policy | Select-Object -ExpandProperty Arn

If (-Not $?) { Write-Error "Failed to create IAM policy. Aborting."; return }

# 4. Attach the policy to the user
Write-Host "Attaching policy to user..."
aws iam attach-user-policy `
    --user-name $UserName `
    --policy-arn $PolicyArn

If (-Not $?) { Write-Error "Failed to attach policy. Aborting."; return }

# 5. Generate an access key
Write-Host "Creating access key..."
$KeyOutput = aws iam create-access-key --user-name $UserName | ConvertFrom-Json

$AccessKeyId = $KeyOutput.AccessKey.AccessKeyId
$SecretAccessKey = $KeyOutput.AccessKey.SecretAccessKey

# 6. Print the results
Write-Host "------------------------------------------------------" -ForegroundColor Green
Write-Host "✅ Participant '$ParticipantId' created successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Copy and securely send this content to the participant:" -ForegroundColor Yellow
Write-Host ""
Write-Host "--- BEGIN .env FILE ---" -ForegroundColor White
Write-Host "AWS_REGION=$AwsRegion"
Write-Host "SUBMISSIONS_BUCKET=$SubmissionsBucket"
Write-Host "PARTICIPANT_ID=$ParticipantId"
Write-Host "AWS_ACCESS_KEY_ID=$AccessKeyId"
Write-Host "AWS_SECRET_ACCESS_KEY=$SecretAccessKey"
Write-Host "--- END .env FILE ---" -ForegroundColor White
Write-Host "------------------------------------------------------"