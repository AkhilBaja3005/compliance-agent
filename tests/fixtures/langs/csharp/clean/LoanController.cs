using Microsoft.AspNetCore.Mvc;
public class LoanController : ControllerBase {
  private readonly HttpClient http = new HttpClient();
  [HttpPost("/v1/loan/decision")]
  public async Task<IActionResult> Decide(Applicant a) {
    var email = Redact(a.Email);
    var r = await http.PostAsync("https://eu-west.llm.example.eu/v1/chat/completions", new StringContent(email));
    await humanReviewQueue.Enqueue(r);
    return Ok("pending_human_review");
  }
}
