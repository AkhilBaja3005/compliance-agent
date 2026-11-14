object Engine { def decide(email: String) = scalaj.http.Http("https://api.openai.com/v1/chat/completions").postData(email).asString }
