import Foundation
func decideLoan(email: String) {
  var req = URLRequest(url: URL(string: "https://api.openai.com/v1/chat/completions")!)
  req.httpBody = email.data(using: .utf8)
  URLSession.shared.dataTask(with: req).resume()
}
