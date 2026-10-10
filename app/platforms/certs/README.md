# Extra trusted certificates (one host each)

| File | Used for | Source | SHA-256 fingerprint | Valid to |
| --- | --- | --- | --- | --- |
| `emsign_root_tls_ca_g1_cross_signed.pem` | `rccd.edu` (Riverside Community College District, CA), `app/platforms/direct_file.py` | The CA's own published issuer file for the site's certificate: `http://repository.emsign.com/certs/EMIncommonDVG2C.p7c`, first certificate in the bundle (fetched 2026-10-10) | `9B:91:34:76:EA:B4:76:E2:1E:08:87:DB:CD:E4:43:45:D1:35:9D:28:11:6B:83:B7:CD:3E:87:BD:80:7E:BF:68` | 2039-07-09 |

**Why.** `rccd.edu` sends its certificate and the InCommon intermediate, but not the last link: "emSign Root TLS CA - G1", which is signed by "emSign Root CA - G1" (a root certifi already trusts). Browsers and macOS fetch the missing link themselves. Python does not, so the check fails with "unable to get local issuer certificate". Shipping the missing link lets Python finish the chain with certificate checking left on.

**Scope.** Only the connections `direct_file.py` makes to `rccd.edu` use it (`_rccd_ssl_context()`). Every other host uses the default trust store. An expired, wrong-host or self-signed certificate is still rejected.

**Refresh.** If `rccd.edu` changes its certificate authority, or this file's `notAfter` date nears, re-fetch the issuer file from the link above and compare. Do not widen the scope.
