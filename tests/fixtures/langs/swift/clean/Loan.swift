import Foundation
func decideLoan(email: String) {
  let safe = redact(email)
  var req = URLRequest(url: URL(string: "https://eu-west.llm.example.eu/v1/chat/completions")!)
  req.httpBody = safe.data(using: .utf8)
  URLSession.shared.dataTask(with: req).resume()
  humanReviewQueue.add(req)
}
