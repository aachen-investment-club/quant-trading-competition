
submit:
	@if [ -z "$$SUBMISSIONS_BUCKET" ] || [ -z "$$PARTICIPANT_ID" ]; then \
		echo "Set SUBMISSIONS_BUCKET and PARTICIPANT_ID (and AWS creds)."; exit 2; \
	fi
	docker run --rm \
		-e AWS_REGION=$$AWS_REGION \
		-e SUBMISSIONS_BUCKET=$$SUBMISSIONS_BUCKET \
		-e PARTICIPANT_ID=$$PARTICIPANT_ID \
		-e AWS_ACCESS_KEY_ID=$$AWS_ACCESS_KEY_ID \
		-e AWS_SECRET_ACCESS_KEY=$$AWS_SECRET_ACCESS_KEY \
		-e AWS_SESSION_TOKEN=$$AWS_SESSION_TOKEN \
		-v "$$(pwd):/usr/src/app" \
		trading-comp-env submit
