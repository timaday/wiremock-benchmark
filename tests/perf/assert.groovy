import java.security.MessageDigest
import java.util.HexFormat
def c = vars.getObject('case_spec')
String expected = c.template == 'static' ? c.example : c.example.replace('0'.repeat(29), vars.get('bench_id'))
boolean valid = prev.getResponseCode() == '200' && prev.getResponseDataAsString() == expected && prev.getTime() + 2 >= vars.get('delay_ms').toLong()
if (!valid) { prev.setSuccessful(false); prev.setResponseMessage('Response status/body/delay assertion failed: ' + prev.getResponseMessage()) }
def digest = MessageDigest.getInstance('SHA-256')
vars.put('request_sha256', HexFormat.of().formatHex(digest.digest(vars.get('body').getBytes('UTF-8'))))
vars.put('response_sha256', HexFormat.of().formatHex(digest.digest(prev.getResponseData())))

vars.remove('body')
