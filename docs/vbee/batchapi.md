# Batch API

**URL**: <https://api.vbee.vn/v1/tts&#x20>;

**Method**: POST

**Tham số Header**

<table data-header-hidden><thead><tr><th width="133"></th><th></th><th></th><th></th><th></th></tr></thead><tbody><tr><td>Tham số</td><td>Giá trị</td><td>Kiểu dữ liệu</td><td>Tính bắt buộc</td><td>Mô tả</td></tr><tr><td>Authorization</td><td>Bearer {{token}}</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td>Token xác thực dạng Bearer: Bearer &#x3C;access_token></td></tr><tr><td>App-Id</td><td>{{app-id}}</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td>ID của ứng dụng người dùng tạo</td></tr><tr><td>Content-Type</td><td>application/json</td><td>String</td><td>Có</td><td>Chỉ định kiểu nội dung JSON</td></tr></tbody></table>

**Cấu trúc body của request**

<table data-header-hidden><thead><tr><th width="132"></th><th width="123"></th><th width="142"></th><th></th></tr></thead><tbody><tr><td>Tham số</td><td>Kiểu dữ liệu</td><td>Tính bắt buộc</td><td>Mô tả</td></tr><tr><td>text</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td><p>Văn bản đầu vào cần tổng hợp. Khoảng trắng đầu cuối sẽ được tự động loại bỏ. Không được để trống. </p><p>Tối đa 100.000 ký tự</p></td></tr><tr><td>mode</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td><p>Chế độ chuyển văn bản. </p><p>*Giá trị bắt buộc là async để sử dụng Batch API.</p></td></tr><tr><td>webhookUrl</td><td>String</td><td>Có</td><td>Webhook để nhận kết quả của request</td></tr><tr><td>voiceCode</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td>Mã giọng đọc dùng để chuyển đổi văn bản.</td></tr><tr><td>outputFormat</td><td><p></p><p></p><p>String</p><p><br></p></td><td><p></p><p></p><p></p><p>Không</p><p><br><br></p></td><td><p>Định dạng loại tệp audio đầu ra</p><p><br></p><p>*Giá trị mặc định: mp3</p><p>*Định dạng đầu ra. Hỗ trợ mp3 và wav.</p><p><br></p><p>Lưu ý: hiện tại chỉ hỗ trợ mp3 và wav, nếu truyền pcm lên thì sẽ tổng hợp văn bản lỗi..</p></td></tr><tr><td>bitrate</td><td><p></p><p></p><p>Number</p><p><br></p></td><td><p></p><p></p><p></p><p>Không</p><p><br><br></p></td><td><p>Tốc độ bit của tệp audio (kbps)</p><p><br></p><p>*Giá trị mặc định: 128</p><p>*Giá trị hợp lệ: 8, 16, 32, 64, 128</p></td></tr><tr><td>speed</td><td><p></p><p></p><p>Number</p><p><br></p></td><td>Không</td><td><p>Tốc độ đọc. </p><p><br></p><p>*Giá trị mặc định: 1.0</p><p>*Giá trị từ 0.25 đến 1.9.</p></td></tr><tr><td>sampleRate</td><td>Number</td><td>Không</td><td><p>Tần số lấy mẫu (Hz). </p><p><br></p><p>*Giá trị mặc định: giá trị cao nhất hỗ trợ cho giọng</p><p>*Giá trị hợp lệ: 8000, 16000, 22050, 24000, 32000, 44100, 48000.</p><p>Lưu ý: tùy vào từng giọng mà có các giá trị mặc định riêng.</p></td></tr><tr><td>emphasisIntensity</td><td>Number</td><td><p></p><p></p><p></p><p>Không</p><p><br><br></p></td><td><p>Mức độ nhấn nhá. </p><p><br></p><p>*Giá trị số nguyên từ 0 đến 100, phải là bội số của 10. </p><p>*Chỉ áp dụng cho một số giọng có hỗ trợ tính năng nhấn nhá.</p></td></tr><tr><td>clientPause</td><td>Object</td><td><p></p><p></p><p></p><p>Không</p><p><br><br></p></td><td>Cấu hình thời gian ngắt nghỉ (xem bảng bên dưới).</td></tr></tbody></table>

**Cấu trúc clientPause**

<table data-header-hidden><thead><tr><th width="148"></th><th width="137"></th><th width="158"></th><th></th></tr></thead><tbody><tr><td>Tham số</td><td>Kiểu dữ liệu</td><td>Tính bắt buộc</td><td>Mô tả</td></tr><tr><td>majorBreak</td><td>Number</td><td>Không</td><td><p>Thời gian ngắt nghỉ dấu chấm phẩy (giây). </p><p><br></p><p>*Giá trị mặc định: 0.3</p><p>*Giá trị từ 0.1 đến 10.</p></td></tr><tr><td>mediumBreak</td><td>Number</td><td>Không</td><td><p>Thời gian ngắt nghỉ dấu phẩy (giây). </p><p><br></p><p>*Giá trị mặc định: 0.25</p><p>*Giá trị từ 0.1 đến 10.</p></td></tr><tr><td>paragraphBreak</td><td>Number</td><td>Không</td><td><p>Thời gian ngắt nghỉ xuống dòng (giây). </p><p><br></p><p>*Giá trị mặc định: 0.6</p><p>*Giá trị từ 0 đến 10.</p></td></tr><tr><td>sentenceBreak</td><td>Number</td><td>Không</td><td><p>Thời gian ngắt nghỉ dấu chấm câu (giây). </p><p><br></p><p>*Giá trị mặc định: 0.45</p><p>*Giá trị từ 0.1 đến 10.</p></td></tr></tbody></table>

**Chú ý:**

\
**Các audio link trả về chỉ có thời hạn trong vòng 3 phút, sau 3 phút audio link sẽ hết hạn và không thể sử dụng. Audio vẫn sẽ được lưu trữ trên hệ thống trong vòng 3 ngày kể từ thời điểm chuyển văn bản thành công. Muốn lấy link mới, bạn gọi api Get Request (bên dưới) để lấy lại audio link mới.**

**Kết quả trả về:**&#x20;

- requestId: ID của request, dùng để tracking
- status: Trạng thái của request
- error_code: mã lỗi
- error_message: Mô tả chi tiết lỗi

<pre><code><strong>//REQUEST EXAMPLE: 
</strong>curl -X POST https://api.vbee.vn/v1/tts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer &#x3C;access_token>" \
  -H "App-Id: your-app-id" \
  -d '{
    "text": "Xin chào, đây là giọng nói tổng hợp từ Vbee.",
    "voiceCode": "hn_female_ngochuyen_full_48k-fhg",
    "mode": "async",
    "outputFormat": "mp3",
    "bitrate": 128,
    "speed": 1.0,
    "webhookUrl": "https://your-domain.com/callback"
  }'
</code></pre>

```
//SUCCESS RESPONSE:
{
  "requestId": "eb75e2b0-ce65-4e85-8450-2d09728d996b",
  "status": "PROCESSING"
}
```

```
//FAILURE RESPONSE:
//Khi có lỗi, response trả về dạng JSON:
{
  "error": {
    "code": "BAD_REQUEST",
    "message": "webhookUrl must be defined at path webhookUrl"
  }
}
```

**Danh sách Error Codes**

<table data-header-hidden><thead><tr><th width="264"></th><th width="126"></th><th></th></tr></thead><tbody><tr><td>Code</td><td>HTTP status</td><td>Mô tả</td></tr><tr><td>UNAUTHORIZED</td><td><p></p><p></p><p>401</p><p><br></p></td><td>Token không hợp lệ, thiếu Authorization header, hoặc thiếu appId (trong body hoặc header app-id)</td></tr><tr><td><p></p><p></p><p></p><p>BAD_REQUEST</p><p><br><br></p></td><td>400</td><td><p>- Body request không hợp lệ. Ví dụ: thiếu trường bắt buộc, sampleRate không hợp lệ</p><p>- Lỗi cấu hình request không hợp lệ (ví dụ: voiceCode không tồn tại)</p></td></tr><tr><td>INTERNAL_SERVER_ERROR</td><td>500</td><td>Lỗi nội bộ</td></tr></tbody></table>
