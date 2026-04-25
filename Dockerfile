FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_server.py .

# Create directory for SQLite database
RUN mkdir -p /app/data

# Set environment variables (override with your production values)
ENV SMTP_HOST=sandbox.smtp.mailtrap.io
ENV SMTP_PORT=587
ENV SMTP_USER=your_smtp_user
ENV SMTP_PASSWORD=your_smtp_password
ENV EMAIL_TO=your_email@example.com
ENV EMAIL_FROM=your_smtp_user
ENV PORT=8001

EXPOSE 8001

CMD ["python", "mcp_server.py"]