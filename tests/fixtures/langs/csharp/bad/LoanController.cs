using Microsoft.AspNetCore.Mvc;
public class LoanController : ControllerBase {
  private readonly HttpClient http = new HttpClient();
  [HttpPost("/v1/loan/decision")]
  public async Task<IActionResult> Decide(Applicant a) {
    var email = a.Email;
    var r = await http.PostAsync("https://api.openai.com/v1/chat/completions", new StringContent(email));
    return Ok("approved");
  }
}
