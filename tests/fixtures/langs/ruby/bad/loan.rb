require "faraday"
class LoanApp < Sinatra::Base
  post "/v1/loan/decision" do
    email = params[:email]
    r = Faraday.post("https://api.openai.com/v1/chat/completions", email)
    "approved"
  end
end
def decide_loan(email)
  Faraday.post("https://api.openai.com/v1/chat/completions", email)
end
