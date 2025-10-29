# ===================================================================
#           Quant Competition - Add Participant Script (v2)
# ===================================================================
# This script creates a new IAM participant user with policies for:
# 1. Uploading submissions to their own S3 folder.
# 2. Reading the active test key from DynamoDB.
# 3. Downloading the active test data from S3.
# ===================================================================

# --- CONFIGURATION (UPDATE THESE) ---
$SubmissionsBucket = "comp-submission-bucket" # <-- !! UPDATE THIS (Bucket for user submissions) !!
$AwsRegion = "eu-central-1" # <-- !! UPDATE THIS (Your AWS Region) !!
$DdbTableArn = "arn:aws:dynamodb:eu-central-1:058264123925:table/trading_competition_scores" # <-- !! UPDATE THIS (Full ARN for the DDB config table) !!
$DataBucketName = "comp-eval-bucket" # <-- !! UPDATE THIS (Name of the S3 bucket containing test data) !!
# ------------------------------------

# Helper function to stop the script on failure
Function Stop-OnError($CommandName, $AwsOutput) {
  Write-Host "------------------------------------------------------" -ForegroundColor Red
  Write-Error "ERROR: The command '$CommandName' failed."
  # Convert the output (which might be an array of lines) to a single string
  $ErrorString = $AwsOutput | Out-String
  Write-Error "AWS Response: $ErrorString"
  Write-Error "Aborting script. Please fix the IAM permissions or script configuration."
  Write-Host "------------------------------------------------------" -ForegroundColor Red
  # Exit the script
  exit 1
}

# 1. Generate a random Participant ID
$TeamName = Read-Host "Enter the Team Name (e.g., 'beta-busters')"

# Basic validation
if ([string]::IsNullOrWhiteSpace($TeamName)) {
    Write-Error "ERROR: Team Name cannot be empty. Aborting."
    exit 1
}

# Sanitize the team name part (lowercase, alphanumeric, hyphens)
$SanitizedTeamName = $TeamName -creplace '[^a-zA-Z0-9-]', '' | ForEach-Object { $_.ToLower() }

if ([string]::IsNullOrWhiteSpace($SanitizedTeamName) -or $SanitizedTeamName.Length -lt 3) {
    Write-Error "ERROR: Sanitized Team Name is too short or invalid. Please use at least 3 alphanumeric characters or hyphens. Aborting."
    exit 1
}

# Generate a short random string
$RandomString = -join (Get-Random -Count 6 -InputObject ([char[]]([char]'a'..[char]'z' + [char]'0'..[char]'9')))

# Combine them to form the final ID
$ParticipantId = "${SanitizedTeamName}_${RandomString}"
$UserName = "quant-comp-user-$ParticipantId"
$PolicyName = "QuantCompPolicy-$ParticipantId"

Write-Host "Creating new participant: $ParticipantId" -ForegroundColor Cyan

# 2. Create the IAM user
Write-Host "Attempting to create user: $UserName"
$UserOutput = aws iam create-user --user-name $UserName --output json 2>&1

if ($LASTEXITCODE -eq 0) {
  Write-Host "Command successful. Parsing JSON output..."
  $UserObject = $UserOutput | Out-String | ConvertFrom-Json
  Write-Host "Successfully created user!"
  Write-Host "User ARN: $($UserObject.User.Arn)"
  # We need the UserObject for later, so we keep it.
} else {
  # The command failed. Call our helper function.
  Stop-OnError "aws iam create-user" $UserOutput
}

# 3. Create the IAM policy
# --- UPDATED POLICY DOCUMENT ---
# This now includes permissions for ddb:GetItem and s3:GetObject
$PolicyDocument = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::$SubmissionsBucket/$ParticipantId/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem"
      ],
      "Resource": [
        "$DdbTableArn"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::$DataBucketName/*"
      ]
    }
  ]
}
"@
# --- END UPDATED POLICY DOCUMENT ---

Write-Host "Creating IAM policy: $PolicyName"
# Capture all output, including errors
$PolicyOutput = aws iam create-policy --policy-name $PolicyName --policy-document $PolicyDocument --output json 2>&1

If ($LASTEXITCODE -eq 0) {
    Write-Host "Command successful. Parsing JSON output..."
    # If the command succeeded, $PolicyOutput is a JSON string. Now we convert it.
    $PolicyObject = $PolicyOutput | Out-String | ConvertFrom-Json
    $PolicyArn = $PolicyObject.Policy.Arn
} Else {
  # This will now print the AccessDenied error cleanly.
  Stop-OnError "aws iam create-policy" $PolicyOutput
}

# 4. Attach the policy to the user
Write-Host "Attaching policy to user..."
# This command doesn't return JSON, so we just check for errors.
$AttachOutput = aws iam attach-user-policy --user-name $UserName --policy-arn $PolicyArn --output json 2>&1
If ($LASTEXITCODE -ne 0) {
  # Our updated Stop-OnError function will handle printing the error.
  Stop-OnError "aws iam attach-user-policy" $AttachOutput
}

# 5. Generate an access key
Write-Host "Creating access key..."
# Capture all output, including errors
$KeyOutput = aws iam create-access-key --user-name $UserName --output json 2>&1

If ($LASTEXITCODE -eq 0) {
    Write-Host "Command successful. Parsing JSON output..."
    # If the command succeeded, $KeyOutput is a JSON string.
    $KeyObject = $KeyOutput | Out-String | ConvertFrom-Json
    $AccessKeyId = $KeyObject.AccessKey.AccessKeyId
    $SecretAccessKey = $KeyObject.AccessKey.SecretAccessKey
} Else {
Stop-OnError "aws iam create-access-key" $KeyOutput
}

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
Write-Host "--- END .env FILE ---"


