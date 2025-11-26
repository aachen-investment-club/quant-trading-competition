#!/bin/bash
# load_test.sh - Simulating 500 concurrent users

for i in {1..500}
do
   # Override the ID for this specific process
   export PARTICIPANT_ID="load_test_user_$i"
   
   # Run submit.py in the background to simulate concurrency
   python tools/submit.py &
done

wait
echo "All 500 submissions fired!"