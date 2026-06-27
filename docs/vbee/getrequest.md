# Get request

**URL**: <https://api.vbee.vn/v1/tts/requests/\\{{requestId\\}}&#x20>;

**Method**: GET

**Tham số Header**

<table data-header-hidden><thead><tr><th width="131"></th><th></th><th></th><th></th><th></th></tr></thead><tbody><tr><td>Tham số</td><td>Giá trị</td><td>Kiểu dữ liệu</td><td>Tính bắt buộc</td><td>Mô tả</td></tr><tr><td>Authorization</td><td>Bearer {{token}}</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td>Token xác thực dạng Bearer: Bearer &#x3C;access_token></td></tr><tr><td>App-Id</td><td>{{app-id}}</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td>ID của ứng dụng người dùng tạo</td></tr><tr><td>Content-Type</td><td>application/json</td><td><br></td><td>Có</td><td>Chỉ định kiểu nội dung JSON</td></tr></tbody></table>

**Tham số Path**

<table data-header-hidden><thead><tr><th width="110"></th><th width="140"></th><th></th><th></th><th></th></tr></thead><tbody><tr><td>Tham số</td><td>Giá trị</td><td>Kiểu dữ liệu</td><td>Tính bắt buộc</td><td>Mô tả</td></tr><tr><td>requestId</td><td>{{requestId}}</td><td><p></p><p></p><p>String</p><p><br></p></td><td>Có</td><td><p></p><p>ID của TTS request cần lấy chi tiết</p><p></p></td></tr></tbody></table>

**Kết quả trả về:**&#x20;

- requestId: ID của request, dùng để tracking
- status: Trạng thái của request
- error_code: mã lỗi
- error_message: Mô tả chi tiết lỗi

```
//REQUEST EXAMPLE:

curl -X GET "https://api.vbee.vn/v1/tts/requests/eb75e2b0-ce65-4e85-8450-2d09728d996b" \
  -H "Authorization: Bearer <access_token>" \
  -H "App-Id: your-app-id"
```

```
//SUCCESSFUL RESPONSE: (status = COMPLETED)

{
  "requestId": "eb75e2b0-ce65-4e85-8450-2d09728d996b",
  "status": "COMPLETED",
  "audioLink": "https://example.com/audio/eb75e2b0.mp3"
}
```

```
//RESPONSE PROCESSING  (status = PROCESSING)

{
  "requestId": "eb75e2b0-ce65-4e85-8450-2d09728d996b",
  "status": "PROCESSING"
}
```

```
//FAILURE RESPONSE (status = `FAILED`)

{
    "error": {
        "code": "BAD_REQUEST",
        "message": "Request is not found"
    }
}
```

**Danh sách Error Codes**

| Code                  | HTTP status                         | Mô tả                                                                                                                                                                |
| --------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UNAUTHORIZED          | <p></p><p></p><p>401</p><p><br></p> | Token không hợp lệ, thiếu Authorization header, hoặc thiếu appId (trong body hoặc header app-id)                                                                     |
| BAD_REQUEST           | 400                                 | <p>- Body request không hợp lệ. Ví dụ: thiếu trường bắt buộc, sampleRate không hợp lệ</p><p>- Lỗi cấu hình request không hợp lệ (ví dụ: voiceCode không tồn tại)</p> |
| INTERNAL_SERVER_ERROR | 500                                 | Lỗi nội bộ                                                                                                                                                           |
