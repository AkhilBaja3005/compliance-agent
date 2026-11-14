<?php
function decide_loan($email) {
  $safe = redact($email);
  $ch = curl_init("https://eu-west.llm.example.eu/v1/chat/completions");
  curl_setopt($ch, CURLOPT_POSTFIELDS, $safe);
  curl_exec($ch);
  human_review_queue_push($ch);
  return "pending_human_review";
}
