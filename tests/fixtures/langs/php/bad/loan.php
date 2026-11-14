<?php
function decide_loan($email) {
  $ch = curl_init("https://api.openai.com/v1/chat/completions");
  curl_setopt($ch, CURLOPT_POSTFIELDS, $email);
  curl_exec($ch);
  return "approved";
}
